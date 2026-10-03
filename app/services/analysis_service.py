from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import update
from app.models.project import Project
from app.models.analysis import AnalysisRun, Finding
from app.analyzers.utils import validate_and_extract_zip, cleanup_temp_dir
from app.analyzers.engine import RuffAnalyzer, BanditAnalyzer, RadonAnalyzer
from app.core.config import settings
from datetime import datetime
import uuid

class AnalysisService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def start_analysis(self, project_id: uuid.UUID, zip_path: str) -> AnalysisRun:
        # 1. Create initial run record
        run = AnalysisRun(
            project_id=project_id,
            status="pending",
            started_at=datetime.utcnow()
        )
        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def execute_analysis_pipeline(self, run_id: uuid.UUID, zip_path: str):
        # We need a new session because this runs in background
        # This is a simplified version; in production, we'd use a session factory
        from app.db.session import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            # Fetch run
            from sqlalchemy.future import select
            res = await db.execute(select(AnalysisRun).where(AnalysisRun.id == run_id))
            run = res.scalar_one_or_none()
            if not run:
                return

            try:
                # Update status to processing
                run.status = "processing"
                await db.commit()

                # 2. Securely extract ZIP
                temp_dir = validate_and_extract_zip(zip_path)

                try:
                    # 3. Run Analyzers
                    analyzers = [RuffAnalyzer(temp_dir), BanditAnalyzer(temp_dir), RadonAnalyzer(temp_dir)]
                    all_findings = []

                    for analyzer in analyzers:
                        all_findings.extend(analyzer.analyze())

                    # 4. Persist findings
                    for finding in all_findings:
                        finding.analysis_run_id = run.id
                        db.add(finding)

                    run.status = "completed"
                    run.finished_at = datetime.utcnow()

                    # Summary
                    run.summary = {
                        "total_findings": len(all_findings),
                        "severity_counts": {
                            "high": len([f for f in all_findings if f.severity == "high"]),
                            "medium": len([f for f in all_findings if f.severity == "medium"]),
                            "low": len([f for f in all_findings if f.severity == "low"]),
                        }
                    }

                finally:
                    # 5. Cleanup temporaries
                    from app.analyzers.utils import cleanup_temp_dir
                    cleanup_temp_dir(temp_dir)

            except Exception as e:
                run.status = "failed"
                run.error_message = str(e)
                run.finished_at = datetime.utcnow()

            await db.commit()
