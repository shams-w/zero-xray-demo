import { useState } from "react";


const TEXT = {
  en: {
    title: "Choose what the agent should change",
    subtitle: "The plan will be rebuilt from these structured choices.",
    packages: "Package",
    duration: "Renewal period",
    year: "year",
    years: "years",
    autoRenewal: "Enable automatic renewal",
    total: "Calculated total",
    packageSubtotal: "Package subtotal",
    mandatoryFees: "Mandatory one-time fees",
    addOns: "Optional add-ons",
    tax: "Tax",
    quantity: "Quantity",
    once: "one time",
    perYear: "per year",
    feePending: "Price confirmed by the connected fee system",
    pricingCheckpoint: "Pricing checkpoint",
    annualFeeRule: "Annual fee rule",
    minimumDue: "Minimum due",
    paymentMethod: "Payment method",
    priority: "Case priority",
    resolution: "Requested outcome",
    preference: "Execution preference",
    inquiryTopic: "Inquiry topic",
    responseChannel: "How should the answer be delivered?",
    apply: "Confirm changes",
    applyPayment: "Confirm and continue to payment",
    cancel: "Cancel",
    priorities: {
      NORMAL: "Normal",
      HIGH: "High",
      URGENT: "Urgent",
    },
    resolutions: {
      INVESTIGATE_AND_RESPOND: "Investigate and respond",
      CORRECT_SERVICE: "Correct the service",
      REFUND_OR_REMEDY: "Refund or remedy",
      HUMAN_FOLLOW_UP: "Human follow-up",
    },
    preferences: {
      STANDARD: "Standard path",
      FASTEST: "Fastest available path",
      ASSISTED: "Human-assisted path",
    },
    inquiryTopics: {
      SERVICE_REQUIREMENTS: "Service requirements",
      FEES: "Fees and prices",
      REQUIRED_DOCUMENTS: "Required documents",
      APPLICATION_STATUS: "Application status",
      GENERAL_INQUIRY: "General inquiry",
    },
    responseChannels: {
      IN_APP: "Show the answer here",
      EMAIL: "Send by email",
      HUMAN_FOLLOW_UP: "Request staff follow-up",
    },
  },
  ar: {
    title: "حدد التعديلات المطلوبة من المساعد",
    subtitle: "سيعيد المساعد بناء الخطة وفق الاختيارات المحددة.",
    packages: "الباقة",
    duration: "مدة التجديد",
    year: "سنة",
    years: "سنوات",
    autoRenewal: "تفعيل التجديد التلقائي",
    total: "الإجمالي المحسوب",
    packageSubtotal: "إجمالي الباقة",
    mandatoryFees: "رسوم إلزامية لمرة واحدة",
    addOns: "خدمات إضافية اختيارية",
    tax: "الضريبة",
    quantity: "العدد",
    once: "لمرة واحدة",
    perYear: "سنويًا",
    feePending: "يؤكد السعر نظام الرسوم المتصل",
    pricingCheckpoint: "نقطة تحديد السعر",
    annualFeeRule: "قاعدة الرسوم السنوية",
    minimumDue: "الحد الأدنى المستحق",
    paymentMethod: "طريقة الدفع",
    priority: "أولوية الحالة",
    resolution: "النتيجة المطلوبة",
    preference: "طريقة التنفيذ",
    inquiryTopic: "موضوع الاستفسار",
    responseChannel: "طريقة استلام الإجابة",
    apply: "تأكيد التعديلات",
    applyPayment: "تأكيد والانتقال للدفع",
    cancel: "إلغاء",
    priorities: {
      NORMAL: "عادية",
      HIGH: "مرتفعة",
      URGENT: "عاجلة",
    },
    resolutions: {
      INVESTIGATE_AND_RESPOND: "التحقيق والرد",
      CORRECT_SERVICE: "تصحيح الخدمة",
      REFUND_OR_REMEDY: "استرداد أو معالجة",
      HUMAN_FOLLOW_UP: "متابعة موظف",
    },
    preferences: {
      STANDARD: "المسار القياسي",
      FASTEST: "أسرع مسار متاح",
      ASSISTED: "مسار بمساعدة موظف",
    },
    inquiryTopics: {
      SERVICE_REQUIREMENTS: "متطلبات الخدمة",
      FEES: "الرسوم والأسعار",
      REQUIRED_DOCUMENTS: "المستندات المطلوبة",
      APPLICATION_STATUS: "حالة الطلب",
      GENERAL_INQUIRY: "استفسار عام",
    },
    responseChannels: {
      IN_APP: "عرض الإجابة هنا",
      EMAIL: "الإرسال عبر البريد الإلكتروني",
      HUMAN_FOLLOW_UP: "طلب متابعة موظف",
    },
  },
};


function PlanOptionsEditor({ plan, lang, busy, onSubmit, onCancel }) {
  const text = TEXT[lang] || TEXT.en;
  const options = plan.edit_options || { mode: "ACTION" };
  const packages = options.packages || [];
  const durations = options.contract_durations || [];
  const oneTimeFees = options.one_time_fees || [];
  const addOns = options.add_ons || [];
  const taxPolicy = options.tax || {};
  const initialPackageId = plan.selected_package_id || packages[0]?.id || "";
  const [selections, setSelections] = useState({
    selected_package_id: initialPackageId,
    contract_years: plan.contract_years || durations[0] || 1,
    auto_renewal: Boolean(plan.auto_renewal),
    add_on_quantities: Object.fromEntries(
      addOns.map((item) => [
        item.id,
        Number(plan.add_on_quantities?.[item.id] ?? item.default_quantity ?? 0),
      ])
    ),
    priority: plan.case_priority || options.priorities?.[0] || "NORMAL",
    requested_resolution:
      plan.requested_resolution ||
      options.resolutions?.[0] ||
      "INVESTIGATE_AND_RESPOND",
    execution_preference:
      plan.execution_preference || options.preferences?.[0] || "STANDARD",
    inquiry_topic:
      plan.inquiry_topic || options.topics?.[0] || "GENERAL_INQUIRY",
    response_channel:
      plan.response_channel || options.response_channels?.[0] || "IN_APP",
  });

  const selectedPackage = packages.find(
    (item) => item.id === selections.selected_package_id
  );
  const unitPrice = selectedPackage?.price_per_year ?? null;
  const years = durations.length ? Number(selections.contract_years) : 1;
  const packageMultiplier = selectedPackage?.billing_period === "ONCE" ? 1 : years;
  const packageSubtotal = unitPrice == null ? null : unitPrice * packageMultiplier;
  const mandatoryFeesTotal = oneTimeFees
    .filter((item) => item.mandatory !== false)
    .reduce((sum, item) => sum + Number(item.amount || 0), 0);
  const addOnsTotal = addOns.reduce((sum, item) => {
    const quantity = Number(selections.add_on_quantities[item.id] || 0);
    const multiplier = item.billing_period === "YEAR" ? years : 1;
    return sum + Number(item.unit_price || 0) * quantity * multiplier;
  }, 0);
  const subtotal = packageSubtotal == null
    ? null
    : packageSubtotal + mandatoryFeesTotal + addOnsTotal;
  const taxAmount = subtotal == null || taxPolicy.status !== "CONFIRMED" || taxPolicy.included_in_displayed_prices
    ? 0
    : subtotal * Number(taxPolicy.rate_percent || 0) / 100;
  const total = subtotal == null ? null : subtotal + taxAmount;
  const feeModel = options.fee_model || plan.fee_model;

  function submit(event) {
    event.preventDefault();
    onSubmit({ selections });
  }

  return (
    <form className="plan-edit-box structured-plan-editor" onSubmit={submit}>
      <div className="plan-editor-heading">
        <strong>{text.title}</strong>
        <small>{text.subtitle}</small>
      </div>

      {options.mode === "PAYMENT" && (
        <>
          {packages.length > 0 && (
            <fieldset className="plan-option-section">
              <legend>{text.packages}</legend>
              <div className="package-option-grid">
                {packages.map((item) => (
                  <label
                    className={
                      selections.selected_package_id === item.id
                        ? "package-option selected"
                        : "package-option"
                    }
                    key={item.id}
                  >
                    <input
                      type="radio"
                      name="package"
                      checked={selections.selected_package_id === item.id}
                      onChange={() =>
                        setSelections({
                          ...selections,
                          selected_package_id: item.id,
                        })
                      }
                    />
                    <strong>{item.name}</strong>
                    {item.description && <small>{item.description}</small>}
                    <span>
                      {item.price_per_year == null
                        ? text.feePending
                        : `${Number(item.price_per_year).toLocaleString()} ${
                            options.currency || "AED"
                          }`}
                    </span>
                  </label>
                ))}
              </div>
            </fieldset>
          )}

          {durations.length > 0 && (
            <fieldset className="plan-option-section">
              <legend>{text.duration}</legend>
              <div className="duration-option-row">
                {durations.map((duration) => (
                  <button
                    type="button"
                    className={
                      Number(selections.contract_years) === duration
                        ? "duration-option selected"
                        : "duration-option"
                    }
                    key={duration}
                    onClick={() =>
                      setSelections({
                        ...selections,
                        contract_years: duration,
                      })
                    }
                  >
                    {duration} {duration === 1 ? text.year : text.years}
                  </button>
                ))}
              </div>
            </fieldset>
          )}

          {options.auto_renewal_available && (
            <label className="renewal-option">
              <input
                type="checkbox"
                checked={selections.auto_renewal}
                onChange={(event) =>
                  setSelections({
                    ...selections,
                    auto_renewal: event.target.checked,
                  })
                }
              />
              <span>{text.autoRenewal}</span>
            </label>
          )}

          {oneTimeFees.length > 0 && (
            <fieldset className="plan-option-section pricing-fee-section">
              <legend>{text.mandatoryFees}</legend>
              {oneTimeFees.map((item) => (
                <div className="pricing-line" key={item.id}>
                  <span>{item.name} <small>({text.once})</small></span>
                  <strong>{Number(item.amount || 0).toLocaleString()} {options.currency || "AED"}</strong>
                </div>
              ))}
            </fieldset>
          )}

          {addOns.length > 0 && (
            <fieldset className="plan-option-section pricing-fee-section">
              <legend>{text.addOns}</legend>
              {addOns.map((item) => (
                <label className="pricing-line pricing-addon" key={item.id}>
                  <span>
                    {item.name}
                    <small>
                      {Number(item.unit_price || 0).toLocaleString()} {options.currency || "AED"} · {item.billing_period === "YEAR" ? text.perYear : text.once}
                    </small>
                  </span>
                  <span className="addon-quantity">
                    <small>{text.quantity}</small>
                    <input
                      type="number"
                      min="0"
                      max="99"
                      value={selections.add_on_quantities[item.id] || 0}
                      onChange={(event) => setSelections({
                        ...selections,
                        add_on_quantities: {
                          ...selections.add_on_quantities,
                          [item.id]: Math.max(0, Math.min(99, Number(event.target.value) || 0)),
                        },
                      })}
                    />
                  </span>
                </label>
              ))}
            </fieldset>
          )}

          <div className="plan-total-box">
            {feeModel === "WEIGHT_BASED_QUOTE" ? (
              <>
                <span>{text.pricingCheckpoint}</span>
                <strong>{options.pricing_checkpoint || text.feePending}</strong>
              </>
            ) : feeModel === "ANNUAL_REVENUE_PERCENTAGE_WITH_MINIMUM" ? (
              <>
                <span>{text.annualFeeRule}</span>
                <strong>{options.fee_policy_label}</strong>
                <small>
                  {text.minimumDue}: {options.minimum_fee_label} · {text.paymentMethod}: {options.payment_method_label}
                </small>
              </>
            ) : (
              <>
                <div className="pricing-breakdown">
                  <span>{text.packageSubtotal}<b>{packageSubtotal == null ? text.feePending : `${packageSubtotal.toLocaleString()} ${options.currency || "AED"}`}</b></span>
                  {mandatoryFeesTotal > 0 && <span>{text.mandatoryFees}<b>{mandatoryFeesTotal.toLocaleString()} {options.currency || "AED"}</b></span>}
                  {addOnsTotal > 0 && <span>{text.addOns}<b>{addOnsTotal.toLocaleString()} {options.currency || "AED"}</b></span>}
                  <span> 
                      {taxPolicy.label || text.tax}
                    <b>
                      {taxPolicy.status === "CONFIRMED"
                      ? `${taxAmount.toLocaleString(undefined, {
                        minimumFractionDigits: 2,
                        maximumFractionDigits: 2,
                      })} ${options.currency || "AED"}`
                      : text.feePending}
                      </b>
                  </span>
                </div>
                <span>{text.total}</span>
                <strong>
                  {total == null
                    ? text.feePending
                    : `${total.toLocaleString(undefined, { minimumFractionDigits: 2,maximumFractionDigits: 2 })} ${options.currency || "AED"}`}
                </strong>
              </>
            )}
          </div>
        </>
      )}

      {options.mode === "CASE" && (
        <>
          <fieldset className="plan-option-section">
            <legend>{text.priority}</legend>
            <div className="duration-option-row">
              {(options.priorities || []).map((priority) => (
                <button
                  type="button"
                  className={
                    selections.priority === priority
                      ? "duration-option selected"
                      : "duration-option"
                  }
                  key={priority}
                  onClick={() => setSelections({ ...selections, priority })}
                >
                  {text.priorities[priority] || priority}
                </button>
              ))}
            </div>
          </fieldset>
          <label className="structured-select-field">
            <span>{text.resolution}</span>
            <select
              value={selections.requested_resolution}
              onChange={(event) =>
                setSelections({
                  ...selections,
                  requested_resolution: event.target.value,
                })
              }
            >
              {(options.resolutions || []).map((resolution) => (
                <option value={resolution} key={resolution}>
                  {text.resolutions[resolution] || resolution}
                </option>
              ))}
            </select>
          </label>
        </>
      )}

      {options.mode === "ACTION" && (
        <fieldset className="plan-option-section">
          <legend>{text.preference}</legend>
          <div className="package-option-grid">
            {(options.preferences || []).map((preference) => (
              <label
                className={
                  selections.execution_preference === preference
                    ? "package-option selected"
                    : "package-option"
                }
                key={preference}
              >
                <input
                  type="radio"
                  name="execution-preference"
                  checked={selections.execution_preference === preference}
                  onChange={() =>
                    setSelections({
                      ...selections,
                      execution_preference: preference,
                    })
                  }
                />
                <strong>{text.preferences[preference] || preference}</strong>
              </label>
            ))}
          </div>
        </fieldset>
      )}

      {options.mode === "INQUIRY" && (
        <>
          <fieldset className="plan-option-section">
            <legend>{text.inquiryTopic}</legend>
            <div className="package-option-grid inquiry-option-grid">
              {(options.topics || []).map((topic) => (
                <label
                  className={
                    selections.inquiry_topic === topic
                      ? "package-option selected"
                      : "package-option"
                  }
                  key={topic}
                >
                  <input
                    checked={selections.inquiry_topic === topic}
                    name="inquiry-topic"
                    onChange={() => setSelections({ ...selections, inquiry_topic: topic })}
                    type="radio"
                  />
                  <strong>{text.inquiryTopics[topic] || topic}</strong>
                </label>
              ))}
            </div>
          </fieldset>

          <fieldset className="plan-option-section">
            <legend>{text.responseChannel}</legend>
            <div className="package-option-grid inquiry-option-grid">
              {(options.response_channels || []).map((channel) => (
                <label
                  className={
                    selections.response_channel === channel
                      ? "package-option selected"
                      : "package-option"
                  }
                  key={channel}
                >
                  <input
                    checked={selections.response_channel === channel}
                    name="response-channel"
                    onChange={() => setSelections({ ...selections, response_channel: channel })}
                    type="radio"
                  />
                  <strong>{text.responseChannels[channel] || channel}</strong>
                </label>
              ))}
            </div>
          </fieldset>
        </>
      )}

      <div className="plan-editor-actions">
        <button disabled={busy}>
          {options.mode === "PAYMENT" ? text.applyPayment : text.apply}
        </button>
        <button type="button" className="secondary" onClick={onCancel}>
          {text.cancel}
        </button>
      </div>
    </form>
  );
}


export default PlanOptionsEditor;
