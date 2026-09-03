import { useLanguage } from "../i18n/useLanguage";


function StandardsPage() {

  const { t } = useLanguage();
  const s = t.standards;

  return (

    <div className="dashboard-page">


      {/* ================= HERO ================= */}

      <section className="dashboard-hero">

        <div>

          <div className="dashboard-hero-top">

            <span className="badge badge-info">
              {s.badge}
            </span>

            <span className="dashboard-sub-status">
              {s.subStatus}
            </span>

          </div>


          <h2>
            {s.heroTitle}
          </h2>


          <p>
            {s.heroText}
          </p>

        </div>

      </section>



      {/* ================= DEFINITION ================= */}

      <section className="dashboard-card">

        <span className="dashboard-kicker">
          {s.s1Kicker}
        </span>

        <h3>
          {s.s1Title}
        </h3>

        <p className="intro-description">

          {s.s1Text}

        </p>


        <div className="three-column-dashboard">

          {
            s.capabilities.map((item) => (

              <div
                className="dashboard-card compact-dashboard-card"
                key={item.n}
              >

                <span className="dashboard-kicker">
                  {item.n}
                </span>

                <h3>
                  {item.title}
                </h3>

                <p className="intro-description">
                  {item.text}
                </p>

              </div>

            ))
          }

        </div>

      </section>



      {/* ================= JOURNEY: TODAY vs FUTURE ================= */}

      <section className="dashboard-card">

        <span className="dashboard-kicker">
          {s.s2Kicker}
        </span>

        <h3>
          {s.s2Title}
        </h3>


        <div className="journey-comparison-grid">


          <div className="dashboard-card">

            <span className="dashboard-kicker">
              {s.journeyTodayKicker}
            </span>

            <h3>
              {s.journeyTodayTitle}
            </h3>

            <div className="journey-list">

              {
                s.journeyToday.map((item, index) => (

                  <div className="journey-row" key={index}>

                    <span className="journey-index">
                      {index + 1}
                    </span>

                    <p>
                      {item}
                    </p>

                  </div>

                ))
              }

            </div>

          </div>



          <div className="dashboard-card proposed-journey-card">

            <span className="dashboard-kicker">
              {s.journeyFutureKicker}
            </span>

            <h3>
              {s.journeyFutureTitle}
            </h3>

            <div className="journey-list">

              {
                s.journeyFuture.map((item, index) => (

                  <div className="journey-row future-journey-row" key={index}>

                    <span className="journey-index">
                      {index + 1}
                    </span>

                    <p>
                      {item}
                    </p>

                  </div>

                ))
              }

            </div>

          </div>


        </div>


        <div className="impact-list">

          {
            s.principles.map((item) => (

              <div className="step-assessment-card" key={item.n}>

                <span className="step-index">
                  {item.n}
                </span>

                <div>

                  <div className="step-assessment-top">
                    <h4>{item.title}</h4>
                  </div>

                  <p className="step-reason">
                    {item.text}
                  </p>

                </div>

              </div>

            ))
          }

        </div>

      </section>



      {/* ================= 8 STAGES ================= */}

      <section className="dashboard-card">

        <span className="dashboard-kicker">
          {s.s3Kicker}
        </span>

        <h3>
          {s.s3Title}
        </h3>

        <p className="intro-description">

          {s.s3Text}

        </p>


        <div className="step-assessment-list">

          {
            s.stages.map((stage) => (

              <div className="step-assessment-card" key={stage.n}>

                <span className="step-index">
                  {stage.n}
                </span>

                <div>

                  <div className="step-assessment-top">
                    <h4>{stage.title}</h4>
                  </div>

                  <p className="step-reason">
                    {stage.text}
                  </p>

                </div>

              </div>

            ))
          }

        </div>

      </section>



      {/* ================= AGENTIC vs NOT ================= */}

      <section className="dashboard-card">

        <span className="dashboard-kicker">
          {s.s4Kicker}
        </span>

        <h3>
          {s.s4Title}
        </h3>


        <div className="journey-comparison-grid">


          <div className="dashboard-card proposed-journey-card">

            <span className="dashboard-kicker">
              {s.isAgenticKicker}
            </span>

            {
              s.isAgentic.map((item, index) => (

                <div className="detail-record" key={index}>

                  <span className="badge badge-good">
                    ✓
                  </span>

                  <span>
                    {item}
                  </span>

                </div>

              ))
            }

          </div>



          <div className="dashboard-card">

            <span className="dashboard-kicker">
              {s.notAgenticKicker}
            </span>

            {
              s.notAgentic.map((item, index) => (

                <div className="detail-record" key={index}>

                  <span className="badge badge-bad">
                    ✕
                  </span>

                  <span>
                    {item}
                  </span>

                </div>

              ))
            }

          </div>


        </div>


        <div className="validation-success">
          {s.s4Note}
        </div>

      </section>



      {/* ================= READINESS CHECKLIST (12 CRITERIA) ================= */}

      <section className="dashboard-card">

        <span className="dashboard-kicker">
          {s.s5Kicker}
        </span>

        <h3>
          {s.s5Title}
        </h3>

        <p className="intro-description">

          {s.s5Text}

        </p>


        <div className="step-assessment-list">

          {
            s.checklist.map((item, index) => (

              <div className="step-assessment-card" key={item.area}>

                <span className="step-index">
                  {
                    String(index + 1).padStart(2, "0")
                  }
                </span>

                <div>

                  <div className="step-assessment-top">

                    <h4>
                      {item.area}
                    </h4>

                    <div className="step-badges">
                      <span className="badge badge-info">
                        {item.evidence}
                      </span>
                    </div>

                  </div>

                  <p className="step-reason">
                    {item.text}
                  </p>

                </div>

              </div>

            ))
          }

        </div>

      </section>


    </div>

  );

}


export default StandardsPage;
