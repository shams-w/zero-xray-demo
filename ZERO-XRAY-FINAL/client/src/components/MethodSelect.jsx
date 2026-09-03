import { useLanguage } from "../i18n/useLanguage";


const METHOD_IDS = ["explain", "image", "pdf", "excel", "word"];


function MethodSelect({ onPick, onBack }) {

  const { t } = useLanguage();

  return (

    <div className="method-select">


      <button className="method-back" onClick={onBack}>
        {t.method.back}
      </button>


      <span className="section-kicker">
        {t.method.kicker}
      </span>


      <h2 className="method-title">
        {t.method.title}
      </h2>


      <p className="method-subtitle">
        {t.method.subtitle}
      </p>


      <div className="method-grid">

        {
          METHOD_IDS.map((id) => (

            <button
              key={id}
              className="method-card"
              onClick={() => onPick(id)}
            >

              <strong>
                {t.method.items[id].title}
              </strong>

              <small>
                {t.method.items[id].sub}
              </small>

            </button>

          ))
        }

      </div>


      <p className="method-note">

        {t.method.note}

      </p>

    </div>

  );

}


export default MethodSelect;
