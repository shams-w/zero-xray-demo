import { useEffect, useState } from "react";
import JSZip from "jszip";
import mammoth from "mammoth";
import * as pdfjsLib from "pdfjs-dist";
import pdfWorker from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { recognize } from "tesseract.js";

import { deriveJourneyFromText } from "../lib/serviceText";
import { useLanguage } from "../i18n/useLanguage";

pdfjsLib.GlobalWorkerOptions.workerSrc = pdfWorker;

const COPY = {
  ar: {
    title: "أدخل بيانات الخدمة",
    autoAnalysis: "تحليل تلقائي",
    hint: "الصق صفحة الخدمة كاملة، أو ارفع ملفًا وسيستخرج النظام بيانات الخدمة وخطواتها تلقائيًا.",
    quickStart: "خدمات جاهزة للتجربة",
    quickStartHint: "اختر خدمة لملء البيانات تلقائيًا، ثم ابدأ التحليل.",
    useTemplate: "استخدام هذه الخدمة",
    flow: ["النص", "استخراج البيانات", "التصنيف", "إعادة التصميم"],
    templates: [
      {
        id: "corporate-po-box-renewal",
        title: "تجديد صندوق بريد للشركات",
        description: "خدمة مدفوعة تتضمن باقات ومددًا وخيارات إضافية.",
        serviceType: "RENEWAL",
        paymentRequirement: "REQUIRED",
        content: `تجديد صندوق بريد للشركات

خدمة تتيح للشركات والمؤسسات الحكومية تجديد صندوق البريد والاستمرار في استلام المراسلات والطرود.

الباقات:
- الباقة الأساسية: 995 درهمًا سنويًا.
- الباقة المميزة: 2,495 درهمًا سنويًا.
- الباقة المميزة بلس: 11,995 درهمًا سنويًا.

مدد الاشتراك المتاحة: سنة واحدة، سنتان، ثلاث سنوات، خمس سنوات، أو عشر سنوات.
رسوم التسجيل الإلزامية: 70 درهمًا لمرة واحدة.
إضافة رخصة تجارية: 995 درهمًا.
إضافة وكيل بريدي: 100 درهم.

إجراءات الخدمة:
1. تسجيل الدخول باستخدام الهوية الرقمية.
2. اختيار صندوق البريد المراد تجديده.
3. التحقق من بيانات الشركة والرخصة التجارية.
4. اختيار الباقة ومدة الاشتراك والخدمات الإضافية.
5. مراجعة المبلغ والموافقة على الخطة.
6. دفع الرسوم.
7. استلام تأكيد التجديد والعقد.`,
      },
      {
        id: "customer-inquiry",
        title: "خدمة استفسارات المتعاملين",
        description: "خدمة معلوماتية مجانية تقدم إجابة موثقة وقابلة للتتبع.",
        serviceType: "INFORMATION",
        paymentRequirement: "NOT_REQUIRED",
        content: `خدمة استفسارات المتعاملين

خدمة معلوماتية تتيح للمتعامل الاستفسار عن خدمات بريد الإمارات، ومتطلبات الأهلية، والرسوم، والمستندات المطلوبة، وحالة الطلب. لا توجد رسوم على الخدمة.

إجراءات الخدمة:
1. تسجيل الدخول باستخدام الهوية الرقمية.
2. اختيار موضوع الاستفسار.
3. إدخال السؤال أو الرقم المرجعي للطلب.
4. يسترجع الوكيل الذكي المعلومات الموثقة من المصادر المعتمدة.
5. يتلقى المتعامل الإجابة مع المصدر أو الرقم المرجعي.
6. يمكن للمتعامل طلب دعم موظف عند الحاجة.`,
      },
    ],
    placeholder: `مثال:

استأجر صندوق بريد الأفراد

تتيح الخدمة الحصول على صندوق بريد آمن.
الباقات: صندوقي 300 درهم، منزلي 695 درهم، منزلي الفوري 995 درهم.
رسوم التسجيل 70 درهم.
وكيل بريدي إضافي 50 درهم.

إجراءات الخدمة:
1. تسجيل الدخول بالهوية الرقمية
2. اختيار الخدمة
3. إدخال البيانات
4. دفع الرسوم
5. استلام رسالة التأكيد`,
    button: "تحليل الخدمة تلقائيًا",
    loading: "جارٍ تحليل الخدمة...",
    extracting: "جارٍ قراءة الملف واستخراج البيانات...",
    required: "اكتب أو الصق بيانات الخدمة أولًا.",
    chooseFile: "اختر الملف أولًا.",
    noText: "لم يتم العثور على نص واضح داخل الملف. جرّب ملفًا أو صورة أوضح.",
    fileFailed: "تعذر قراءة الملف. تأكد من نوع الملف ثم حاول مرة أخرى.",
    back: "→ رجوع لاختيار طريقة التحليل",
    clickFile: "اضغط لاختيار الملف",
    selectedFile: "الملف المختار",
    uploadHint: "سيقرأ النظام الملف ويستخرج بيانات الخدمة وخطواتها تلقائيًا.",
    extractedPreview: "النص المستخرج",
  },
  en: {
    title: "Enter service information",
    autoAnalysis: "AUTO ANALYSIS",
    hint: "Paste the complete service page, or upload a file and the system will extract the service data and steps automatically.",
    quickStart: "Ready-to-use services",
    quickStartHint: "Choose a service to fill in its information, then start the analysis.",
    useTemplate: "Use this service",
    flow: ["Text", "Data extraction", "Classification", "Redesign"],
    templates: [
      {
        id: "corporate-po-box-renewal",
        title: "Renew Corporate P.O. Box",
        description: "A paid service with packages, durations and optional add-ons.",
        serviceType: "RENEWAL",
        paymentRequirement: "REQUIRED",
        content: `Renew Corporate P.O. Box

This service allows companies and government entities to renew a P.O. Box and continue receiving correspondence and parcels.

Packages:
- Basic: AED 995 per year.
- Premium: AED 2,495 per year.
- Premium+: AED 11,995 per year.

Available contract periods: 1, 2, 3, 5 or 10 years.
Mandatory registration fee: AED 70, paid once.
Additional trade licence: AED 995.
Additional postal agent: AED 100.

Service steps:
1. Sign in with UAE PASS.
2. Select the P.O. Box to renew.
3. Verify the company and trade licence information.
4. Choose the package, contract period and optional add-ons.
5. Review the amount and approve the plan.
6. Pay the fees.
7. Receive the renewal confirmation and contract.`,
      },
      {
        id: "customer-inquiry",
        title: "Customer Inquiry Service",
        description: "A free information service with a sourced, traceable answer.",
        serviceType: "INFORMATION",
        paymentRequirement: "NOT_REQUIRED",
        content: `Customer Inquiry Service

An information service that allows customers to ask about Emirates Post services, eligibility requirements, fees, required documents and application status. The service has no fee.

Service steps:
1. Sign in with UAE PASS.
2. Select the inquiry topic.
3. Enter the question or application reference number.
4. The intelligent agent retrieves verified information from approved sources.
5. The customer receives the answer with its source or reference.
6. The customer may request staff support when needed.`,
      },
    ],
    placeholder: "Paste the service name, description, fees and steps here...",
    button: "Analyse automatically",
    loading: "Analysing service...",
    extracting: "Reading the file and extracting service data...",
    required: "Enter the service information first.",
    chooseFile: "Please select a file first.",
    noText: "No readable text was found in the file. Try a clearer file or image.",
    fileFailed: "The file could not be read. Check the file type and try again.",
    back: "← Back to analysis method",
    clickFile: "Click to choose a file",
    selectedFile: "Selected file",
    uploadHint: "The system will read the file and automatically extract the service information and steps.",
    extractedPreview: "Extracted text",
  },
};

function cleanExtractedText(value = "") {
  return value
    .replace(/\u0000/g, "")
    .replace(/[ \t]+\n/g, "\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

async function extractTextFromImage(file) {
  const result = await recognize(file, "ara+eng");
  return cleanExtractedText(result?.data?.text || "");
}

async function extractTextFromPdf(file) {
  const buffer = await file.arrayBuffer();
  const pdf = await pdfjsLib.getDocument({ data: new Uint8Array(buffer) }).promise;

  const textPages = [];

  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber += 1) {
    const page = await pdf.getPage(pageNumber);
    const content = await page.getTextContent();
    const pageText = content.items
      .map((item) => ("str" in item ? item.str : ""))
      .join(" ")
      .trim();

    if (pageText) {
      textPages.push(pageText);
    }
  }

  const directText = cleanExtractedText(textPages.join("\n\n"));
  if (directText.length >= 20) return directText;

  // Fallback OCR for scanned/image-only PDFs.
  const ocrPages = [];
  const maxOcrPages = Math.min(pdf.numPages, 8);

  for (let pageNumber = 1; pageNumber <= maxOcrPages; pageNumber += 1) {
    const page = await pdf.getPage(pageNumber);
    const viewport = page.getViewport({ scale: 1.6 });

    const canvas = document.createElement("canvas");
    const context = canvas.getContext("2d");

    canvas.width = Math.ceil(viewport.width);
    canvas.height = Math.ceil(viewport.height);

    await page.render({
      canvasContext: context,
      viewport,
    }).promise;

    const result = await recognize(canvas, "ara+eng");
    const pageText = cleanExtractedText(result?.data?.text || "");
    if (pageText) ocrPages.push(pageText);
  }

  return cleanExtractedText(ocrPages.join("\n\n"));
}

async function extractTextFromWord(file) {
  const arrayBuffer = await file.arrayBuffer();
  const result = await mammoth.extractRawText({ arrayBuffer });
  return cleanExtractedText(result?.value || "");
}

function xmlText(node) {
  return node?.textContent?.trim() || "";
}

async function extractTextFromExcel(file) {
  const zip = await JSZip.loadAsync(await file.arrayBuffer());

  let sharedStrings = [];
  const sharedStringsFile = zip.file("xl/sharedStrings.xml");

  if (sharedStringsFile) {
    const sharedXml = await sharedStringsFile.async("string");
    const sharedDoc = new DOMParser().parseFromString(sharedXml, "application/xml");
    sharedStrings = Array.from(sharedDoc.getElementsByTagName("si")).map((si) =>
      Array.from(si.getElementsByTagName("t"))
        .map((t) => xmlText(t))
        .join("")
    );
  }

  const sheetNames = Object.keys(zip.files)
    .filter((name) => /^xl\/worksheets\/sheet\d+\.xml$/i.test(name))
    .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));

  const rows = [];

  for (const sheetName of sheetNames) {
    const xml = await zip.file(sheetName).async("string");
    const doc = new DOMParser().parseFromString(xml, "application/xml");

    for (const row of Array.from(doc.getElementsByTagName("row"))) {
      const cells = [];

      for (const cell of Array.from(row.getElementsByTagName("c"))) {
        const type = cell.getAttribute("t");
        const valueNode = cell.getElementsByTagName("v")[0];
        const inlineNode = cell.getElementsByTagName("is")[0];

        let value = "";

        if (type === "s" && valueNode) {
          value = sharedStrings[Number(xmlText(valueNode))] || "";
        } else if (type === "inlineStr" && inlineNode) {
          value = Array.from(inlineNode.getElementsByTagName("t"))
            .map((t) => xmlText(t))
            .join("");
        } else if (valueNode) {
          value = xmlText(valueNode);
        }

        if (value) cells.push(value);
      }

      if (cells.length) rows.push(cells.join(" | "));
    }
  }

  return cleanExtractedText(rows.join("\n"));
}

async function extractTextFromFile(file, method) {
  switch (method) {
    case "image":
      return extractTextFromImage(file);
    case "pdf":
      return extractTextFromPdf(file);
    case "word":
      return extractTextFromWord(file);
    case "excel":
      return extractTextFromExcel(file);
    default:
      return "";
  }
}

function ServiceForm({ method, onBack, onAnalyze, loading, error }) {
  const { lang } = useLanguage();
  const copy = COPY[lang] || COPY.en;

  const [rawText, setRawText] = useState("");
  const [selectedFile, setSelectedFile] = useState(null);
  const [selectedTemplateId, setSelectedTemplateId] = useState(null);
  const [localError, setLocalError] = useState("");
  const [isExtracting, setIsExtracting] = useState(false);

  useEffect(() => {
    if (!selectedTemplateId) return;

    const selectedTemplate = copy.templates.find(
      (template) => template.id === selectedTemplateId
    );

    if (selectedTemplate) setRawText(selectedTemplate.content);
  }, [copy.templates, selectedTemplateId]);

  useEffect(() => {
    setSelectedFile(null);
    setLocalError("");

    if (method !== "explain") {
      setRawText("");
      setSelectedTemplateId(null);
    }
  }, [method]);

  const methodConfig = {
    explain: {
      title: lang === "ar" ? "اشرح الخدمة بنفسك" : "Describe the service",
      accept: null,
    },
    image: {
      title: lang === "ar" ? "ارفع صورة الخدمة" : "Upload service image",
      accept: "image/*",
    },
    pdf: {
      title: lang === "ar" ? "ارفع ملف PDF" : "Upload PDF",
      accept: ".pdf,application/pdf",
    },
    excel: {
      title: lang === "ar" ? "ارفع ملف Excel" : "Upload Excel",
      accept:
        ".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
    word: {
      title: lang === "ar" ? "ارفع ملف Word" : "Upload Word",
      accept:
        ".docx,application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    },
  };

  const activeMethod = methodConfig[method] || methodConfig.explain;

  async function handleSubmit(event) {
    event.preventDefault();

    if (method === "explain" && !rawText.trim()) {
      setLocalError(copy.required);
      return;
    }

    if (method !== "explain" && !selectedFile) {
      setLocalError(copy.chooseFile);
      return;
    }

    setLocalError("");

    let cleanedText = rawText.trim();

    try {
      if (method !== "explain") {
        setIsExtracting(true);
        cleanedText = await extractTextFromFile(selectedFile, method);
        setRawText(cleanedText);
      }

      if (!cleanedText) {
        setLocalError(copy.noText);
        return;
      }

      const journey = deriveJourneyFromText(cleanedText);

      const fallbackSteps = cleanedText
        .split(/\r?\n/)
        .map((line) => line.trim())
        .filter(Boolean);

      const extractedSteps =
        journey.steps.length > 0 ? journey.steps : fallbackSteps;

      const selectedTemplate = copy.templates.find(
        (template) => template.id === selectedTemplateId
      );

      await Promise.resolve(
        onAnalyze({
          service_name:
            journey.serviceName ||
            (lang === "ar"
              ? "خدمة مستخرجة تلقائيًا"
              : "Automatically extracted service"),

          description: cleanedText,

          service_type: selectedTemplate?.serviceType || null,
          payment_requirement: selectedTemplate?.paymentRequirement || null,

          department: "",
          lang,

          steps: extractedSteps,

          protected_steps: [],
          documents: [],
          actors: [],
          approvals: [],
          waiting_times: [],
          manual_actions: [],
          digital_actions: [],
          dependencies: [],
          branch_visits: 0,
        })
      );
    } catch (fileError) {
      console.error("Service file extraction failed:", fileError);
      setLocalError(copy.fileFailed);
    } finally {
      setIsExtracting(false);
    }
  }

  const isBusy = loading || isExtracting;

  return (
    <div className="service-entry-layout single-entry-layout">
      <button
        type="button"
        className="service-form-back"
        onClick={onBack}
        disabled={isBusy}
      >
        {copy.back}
      </button>

      <section className="service-intro-card">
        <div className="intro-badge">{copy.autoAnalysis}</div>

        <h2>{copy.title}</h2>

        <p className="intro-description">{copy.hint}</p>

        <div className="analysis-flow">
          {copy.flow.map((item, index) => (
            <div className="analysis-flow-item" key={item}>
              <span>{item}</span>
              {index < copy.flow.length - 1 && <b aria-hidden="true">→</b>}
            </div>
          ))}
        </div>

        {method === "explain" && (
          <div className="service-template-section">
            <div className="service-template-heading">
              <strong>{copy.quickStart}</strong>
              <small>{copy.quickStartHint}</small>
            </div>

            <div className="service-template-grid">
              {copy.templates.map((template) => (
                <button
                  className={
                    selectedTemplateId === template.id
                      ? "service-template-card selected"
                      : "service-template-card"
                  }
                  key={template.id}
                  onClick={() => {
                    setSelectedTemplateId(template.id);
                    setRawText(template.content);
                    setLocalError("");
                  }}
                  type="button"
                  disabled={isBusy}
                >
                  <span className="service-template-check" aria-hidden="true">
                    {selectedTemplateId === template.id ? "✓" : "Ø"}
                  </span>
                  <strong>{template.title}</strong>
                  <small>{template.description}</small>
                  <em>{copy.useTemplate}</em>
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      <form className="service-form-card" onSubmit={handleSubmit}>
        {method === "explain" ? (
          <label className="form-field">
            <span>{activeMethod.title}</span>

            <textarea
              rows={22}
              value={rawText}
              onChange={(event) => {
                setRawText(event.target.value);
                setSelectedTemplateId(null);
                setLocalError("");
              }}
              placeholder={copy.placeholder}
              required
              disabled={isBusy}
            />
          </label>
        ) : (
          <div className="service-upload-area">
            <span className="section-kicker">{activeMethod.title}</span>

            <label className="service-file-drop">
              <strong>
                {selectedFile ? selectedFile.name : copy.clickFile}
              </strong>

              <small>
                {selectedFile
                  ? `${copy.selectedFile}: ${selectedFile.name}`
                  : copy.uploadHint}
              </small>

              <input
                type="file"
                accept={activeMethod.accept}
                disabled={isBusy}
                onChange={(event) => {
                  const file = event.target.files?.[0] || null;
                  setSelectedFile(file);
                  setRawText("");
                  setLocalError("");
                }}
              />
            </label>

            {rawText && (
              <label className="form-field extracted-text-preview">
                <span>{copy.extractedPreview}</span>
                <textarea
                  rows={10}
                  value={rawText}
                  onChange={(event) => setRawText(event.target.value)}
                  disabled={isBusy}
                />
              </label>
            )}
          </div>
        )}

        {(localError || error) && (
          <div className="form-error">{localError || error}</div>
        )}

        <button
          className="analyze-button"
          type="submit"
          disabled={isBusy}
        >
          {isExtracting
            ? copy.extracting
            : loading
              ? copy.loading
              : copy.button}
        </button>
      </form>
    </div>
  );
}

export default ServiceForm;