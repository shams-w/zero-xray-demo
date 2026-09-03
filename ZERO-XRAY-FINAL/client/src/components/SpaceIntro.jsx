import { useEffect, useMemo, useState } from "react";
import { useLanguage } from "../i18n/useLanguage";

function SpaceIntro({ onZero }) {
  const { t, lang } = useLanguage();

  const [stage, setStage] = useState(0);
  const [isZeroing, setIsZeroing] = useState(false);
  const [zeroStep, setZeroStep] = useState(0);

  const stars = useMemo(
    () =>
      Array.from({ length: 90 }, (_, index) => ({
        id: index,
        top: Math.random() * 100,
        left: Math.random() * 100,
        size: Math.random() * 2 + 0.6,
        delay: Math.random() * 4,
        duration: 2.4 + Math.random() * 3,
      })),
    []
  );

  useEffect(() => {
    const subtitleTimer = setTimeout(() => {
      setStage(1);
    }, 900);

    const buttonTimer = setTimeout(() => {
      setStage(2);
    }, 1600);

    return () => {
      clearTimeout(subtitleTimer);
      clearTimeout(buttonTimer);
    };
  }, []);

const zeroMessages = {
  ar: [
    "تحليل الخدمة",
    "اكتشاف التعقيد",
    "إعادة تصميم الرحلة",
    "ZERO",
  ],

  en: [
    "Analyzing Service",
    "Detecting Complexity",
    "Redesigning Journey",
    "ZERO",
  ],
};

const activeZeroMessages = zeroMessages[lang] || zeroMessages.en;

  function handleZeroClick() {
    if (isZeroing) return;

    setIsZeroing(true);
    setZeroStep(0);

    let step = 0;

    const interval = setInterval(() => {
      step += 1;
      setZeroStep(step);

      if (step >= activeZeroMessages.length - 1) {
        clearInterval(interval);

        setTimeout(() => {
          onZero();
        }, 700);
      }
    }, 550);
  }

  return (
    <main
      className={`space-intro ${
        isZeroing ? "space-intro-zeroing" : ""
      }`}
    >
      <div className="space-starfield" aria-hidden="true">
        {stars.map((star) => (
          <span
            key={star.id}
            className="space-star"
            style={{
              top: `${star.top}%`,
              left: `${star.left}%`,
              width: `${star.size}px`,
              height: `${star.size}px`,
              animationDelay: `${star.delay}s`,
              animationDuration: `${star.duration}s`,
            }}
          />
        ))}

        <span className="space-shoot space-shoot-a" />
        <span className="space-shoot space-shoot-b" />

        <div className="space-nebula" />

      </div>

      <section className="space-intro-content">
        <span className="space-kicker">
          {t.intro.kicker}
        </span>

        <h1
          className="space-title"
          dir="ltr"
          aria-label={t.intro.title}
        >
          {t.intro.title.split("").map((char, index) => (
            <span
              key={`${char}-${index}`}
              className="space-char"
              style={{
                animationDelay: `${index * 55}ms`,
              }}
            >
              {char === " " ? "\u00A0" : char}
            </span>
          ))}
        </h1>

        {stage >= 1 && (
          <p className="space-subtitle space-fade-up">
            {t.intro.subtitle}
          </p>
        )}

        {stage >= 2 && (
          <div className="space-action space-fade-up">
            <button
              className="zero-button"
              onClick={handleZeroClick}
              type="button"
              aria-label={t.intro.startAnalysis}
              disabled={isZeroing}
            >
              <span
                className="zero-button-rings"
                aria-hidden="true"
              />

              <span
                className="zero-button-glow"
                aria-hidden="true"
              />

              <span className="zero-button-label">
                {isZeroing
                  ? activeZeroMessages[zeroStep]
                  : t.intro.startAnalysis}
              </span>

              {!isZeroing && (
                <span className="zero-button-sub">
                  {t.intro.startHint}
                </span>
              )}
            </button>

<span className="space-action-note">
  <span>{lang === "ar" ? "اكتشاف" : "Detect"}</span>
  <b>·</b>
  <span>{lang === "ar" ? "تصفير" : "Zero"}</span>
  <b>·</b>
  <span>{lang === "ar" ? "تنفيذ" : "Execute"}</span>
</span>
          </div>
        )}
      </section>
    </main>
  );
}

export default SpaceIntro;