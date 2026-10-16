/**
 * NIom's body: a small robot drawn in SVG and animated in CSS.
 *
 * The figure is one inline `<svg>` — no image, no font, no animation library —
 * so it stays sharp at any size, weighs nothing, and recolours itself from the
 * design tokens when the theme changes. React's only job is to put the current
 * state on `data-state`; every movement below is a CSS animation or transition
 * keyed off it, so a token arriving mid-answer never re-mounts anything.
 *
 * Accessibility: the figure is decorative (`aria-hidden`) and says nothing to a
 * screen reader — what the agent is doing is already said in words by the chat's
 * own status line, which is the accessible source of truth. Nothing here is
 * focusable, so a keyboard user is never asked to tab past a face. Hover and
 * focus reactions are CSS only (`:hover` on the panel), which is why they are not
 * part of `RobotState`: a touch screen simply never triggers them.
 *
 * Motion: every animation lives under `.sw-robot` in `index.css`, and each state
 * also differs *statically* (eye shape, laptop, posture), so the global
 * `prefers-reduced-motion` rule — which collapses durations to nothing — leaves a
 * still robot that still communicates which state it is in.
 */

import React, { useEffect, useState } from 'react';
import { cx } from './ui/cx';

/** What the robot can be doing. Driven by the chat's real request state. */
export type RobotState =
    'idle' | 'attentive' | 'thinking' | 'typing' | 'success' | 'error' | 'user-sent';

export interface RobotProps {
    state?: RobotState;
    /** Square size in px; the drawing scales, the stroke weights stay legible. */
    size?: number;
    className?: string;
}

export const Robot: React.FC<RobotProps> = ({ state = 'idle', size = 72, className }) => {
    // A tab nobody is looking at should not keep a mascot breathing. The class
    // is own-rooted, so nothing global is added and the listener goes away with
    // the component.
    const [hidden, setHidden] = useState(() => document.hidden);

    useEffect(() => {
        const onVisibility = () => setHidden(document.hidden);
        document.addEventListener('visibilitychange', onVisibility);
        return () => document.removeEventListener('visibilitychange', onVisibility);
    }, []);

    return (
        <svg
            width={size}
            height={size}
            viewBox="0 0 120 120"
            data-state={state}
            className={cx('sw-robot', hidden && 'sw-robot--paused', className)}
            aria-hidden="true"
            focusable="false"
        >
            {/* Contact shadow: it breathes with the body, which is what sells the weight. */}
            <ellipse className="sw-robot__shadow" cx="60" cy="113" rx="23" ry="3.5" />

            <g className="sw-robot__torso">
                <rect className="sw-robot__plate" x="40" y="70" width="40" height="32" rx="12" />
                {/* Three status LEDs: they are the "thinking" tell when the eyes look away. */}
                <g className="sw-robot__leds">
                    <circle className="sw-robot__led" cx="52" cy="84" r="2.6" />
                    <circle className="sw-robot__led" cx="60" cy="84" r="2.6" />
                    <circle className="sw-robot__led" cx="68" cy="84" r="2.6" />
                </g>
            </g>

            {/* Held in front of the torso, so it covers the LEDs while it is out. */}
            <g className="sw-robot__laptop">
                <rect className="sw-robot__screen" x="43" y="83" width="34" height="18" rx="2.5" />
                <g className="sw-robot__code">
                    <rect
                        className="sw-robot__code-line"
                        x="47"
                        y="88"
                        width="16"
                        height="2.2"
                        rx="1.1"
                    />
                    <rect
                        className="sw-robot__code-line"
                        x="47"
                        y="92.5"
                        width="22"
                        height="2.2"
                        rx="1.1"
                    />
                    <rect
                        className="sw-robot__code-line"
                        x="47"
                        y="97"
                        width="9"
                        height="2.2"
                        rx="1.1"
                    />
                    <rect
                        className="sw-robot__caret"
                        x="58"
                        y="96"
                        width="2.2"
                        height="4.4"
                        rx="1"
                    />
                </g>
                <path className="sw-robot__keyboard" d="M38 101 h44 l-5 6.5 H43 Z" />
            </g>

            <g className="sw-robot__arm sw-robot__arm--left">
                <rect className="sw-robot__plate" x="31" y="72" width="8.5" height="19" rx="4.25" />
            </g>
            <g className="sw-robot__arm sw-robot__arm--right">
                <rect
                    className="sw-robot__plate"
                    x="80.5"
                    y="72"
                    width="8.5"
                    height="19"
                    rx="4.25"
                />
            </g>

            <rect className="sw-robot__neck" x="54" y="63" width="12" height="9" rx="3" />

            <g className="sw-robot__head">
                <rect className="sw-robot__face" x="27" y="22" width="66" height="48" rx="16" />
                <g className="sw-robot__antenna">
                    <path className="sw-robot__antenna-stem" d="M60 22 V13" />
                    <circle className="sw-robot__antenna-tip" cx="60" cy="10.5" r="3.6" />
                </g>

                {/* Open eyes (the default), and the same eyes closed into a smile. */}
                <g className="sw-robot__eyes">
                    <g className="sw-robot__eye sw-robot__eye--left">
                        <rect
                            className="sw-robot__pupil"
                            x="42"
                            y="38"
                            width="10"
                            height="13.5"
                            rx="5"
                        />
                    </g>
                    <g className="sw-robot__eye sw-robot__eye--right">
                        <rect
                            className="sw-robot__pupil"
                            x="68"
                            y="38"
                            width="10"
                            height="13.5"
                            rx="5"
                        />
                    </g>
                </g>
                <g className="sw-robot__grin" fill="none">
                    <path d="M44 40 q6 -6 12 0" />
                    <path d="M64 40 q6 -6 12 0" />
                </g>

                {/* A faint speaker bar: the only thing that reads as a mouth at rest. */}
                <rect className="sw-robot__grill" x="52" y="58" width="16" height="3.4" rx="1.7" />
            </g>

            {/* Above the head and to the side, as if it were being chewed over. */}
            <g className="sw-robot__thinking">
                <circle className="sw-robot__thought" cx="94" cy="30" r="2.6" />
                <circle className="sw-robot__thought" cx="99" cy="22" r="2.6" />
                <circle className="sw-robot__thought" cx="104" cy="14" r="2.6" />
            </g>

            {/* One flash of the accent, when the answer landed. */}
            <g className="sw-robot__sparkle">
                <path d="M96 46 v9 M91.5 50.5 h9" />
            </g>
        </svg>
    );
};

export default Robot;
