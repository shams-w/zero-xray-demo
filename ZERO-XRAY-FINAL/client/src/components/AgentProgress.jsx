import { useEffect, useState } from "react";
import { useLanguage } from "../i18n/useLanguage";


function StepOrbit({ total, remaining, size = 190, label }) {

  const safeTotal = Math.max(total, 1);
  const removed = Math.max(total - remaining, 0);
  const percent =
    total > 0
      ? Math.round((removed / total) * 100)
      : 0;

  const radius = size / 2 - 14;
  const trackRadius = radius - 18;
  const cx = size / 2;
  const cy = size / 2;

  const circumference = 2 * Math.PI * trackRadius;
  const dash = circumference * (remaining / safeTotal);

  const dots = Array.from({ length: safeTotal }).map((_, index) => {

    const angle =
      (index / safeTotal) * 2 * Math.PI - Math.PI / 2;

    return {
      x: cx + radius * Math.cos(angle),
      y: cy + radius * Math.sin(angle),
      removedFlag: index < removed,
      index,
    };

  });


  return (

    <svg
      width={size}
      height={size}
      viewBox={`0 0 ${size} ${size}`}
      className="orbit-svg"
    >

      <circle
        cx={cx}
        cy={cy}
        r={trackRadius}
        fill="none"
        stroke="#241E66"
        strokeWidth="9"
      />

      <circle
        cx={cx}
        cy={cy}
        r={trackRadius}
        fill="none"
        stroke="#7048FF"
        strokeWidth="9"
        strokeLinecap="round"
        strokeDasharray={`${dash} ${circumference}`}
        transform={`rotate(-90 ${cx} ${cy})`}
        style={{ transition: "stroke-dasharray 0.9s cubic-bezier(.4,0,.2,1)" }}
      />

      {
        dots.map((dot) => (

          <circle
            key={dot.index}
            cx={dot.x}
            cy={dot.y}
            r={dot.removedFlag ? 2.6 : 4.2}
            fill={dot.removedFlag ? "#FF5C7A" : "#F0A93A"}
            opacity={dot.removedFlag ? 0.35 : 1}
            style={{ transition: "all 0.6s ease" }}
          />

        ))
      }

      <text
        x={cx}
        y={cy - 2}
        textAnchor="middle"
        fontSize={size * 0.16}
        fontWeight="800"
        fill="#F7F7FB"
      >
        {percent}%
      </text>

      <text
        x={cx}
        y={cy + size * 0.13}
        textAnchor="middle"
        fontSize={size * 0.06}
        fill="#B8BDD3"
        letterSpacing="1.5"
      >
        {label}
      </text>

    </svg>

  );

}


function AgentPipeline({ agents, activeIndex, statusLabels }) {

  return (

    <div className="agent-pipeline" role="list">

      {
        agents.map((agentName, index) => {

          const status =
            index < activeIndex
              ? "done"
              : index === activeIndex
                ? "active"
                : "pending";

          const statusLabel =
            status === "done"
              ? statusLabels.done
              : status === "active"
                ? statusLabels.active
                : statusLabels.pending;

          return (

            <div
              className="agent-pipeline-item"
              key={agentName}
              role="listitem"
            >

              <div className={`agent-node agent-node--${status}`}>

                <span className="agent-node-ring" aria-hidden="true" />

                <span className="agent-node-core" aria-hidden="true">
                  {
                    status === "done" ? (
                      <svg viewBox="0 0 20 20" width="14" height="14" aria-hidden="true">
                        <path
                          fill="currentColor"
                          d="M8 13.4 4.6 10l-1.4 1.4L8 16.2l9-9-1.4-1.4z"
                        />
                      </svg>
                    ) : (
                      index + 1
                    )
                  }
                </span>

              </div>

              <div className="agent-node-label">
                <strong>{agentName}</strong>
                <span>{statusLabel}</span>
              </div>

              {
                index < agents.length - 1 && (
                  <span
                    className={
                      index < activeIndex
                        ? "agent-connector agent-connector--done"
                        : "agent-connector"
                    }
                    aria-hidden="true"
                  >
                    <span className="agent-connector-pulse" />
                  </span>
                )
              }

            </div>

          );

        })
      }

    </div>

  );

}



function AgentProgress({ totalSteps = 8 }) {

  const { t } = useLanguage();

  const messages = t.progress.messages;
  const agents = t.progress.agents || [];

  const [messageIndex, setMessageIndex] = useState(0);
  const [progress, setProgress] = useState(0);


  useEffect(() => {

    const messageTimer = setInterval(() => {
      setMessageIndex((index) => (index + 1) % messages.length);
    }, 900);

    const progressTimer = setInterval(() => {
      setProgress((value) => Math.min(value + 3 + Math.random() * 5, 96));
    }, 180);

    return () => {
      clearInterval(messageTimer);
      clearInterval(progressTimer);
    };

  }, [messages.length]);


  const liveRemaining =
    Math.round(
      totalSteps -
      (totalSteps * (progress / 100))
    );


  return (

    <div className="agent-progress">

      <span className="agent-progress-scanline" aria-hidden="true" />

      <div className="agent-progress-particles" aria-hidden="true">
        {
          Array.from({ length: 10 }).map((_, index) => (
            <span key={index} className={`agent-particle agent-particle-${index}`} />
          ))
        }
      </div>


      <StepOrbit
        total={totalSteps}
        remaining={Math.max(liveRemaining, Math.ceil(totalSteps * 0.15))}
        label={t.progress.unit}
      />


      <h3 className="agent-progress-title">
        {t.progress.title}
      </h3>


      <p className="agent-progress-message" aria-live="polite">

        {messages[messageIndex]}

      </p>


      <div className="progress-track">

        <div
          className="progress-fill"
          style={{ width: `${progress}%` }}
        />

      </div>


      {
        agents.length > 0 && (

          <AgentPipeline
            agents={agents}
            activeIndex={messageIndex}
            statusLabels={{
              pending: t.progress.agentStatusPending,
              active: t.progress.agentStatusActive,
              done: t.progress.agentStatusDone,
            }}
          />

        )
      }

    </div>

  );

}


export default AgentProgress;
