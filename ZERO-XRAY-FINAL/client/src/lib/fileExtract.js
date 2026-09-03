function cleanLines(text) {

  return text
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean)
    .join("\n");

}


export async function extractFromExcel(file) {

  const { default: JSZip } = await import("jszip");
  const buffer = await file.arrayBuffer();

  if (file.name.toLowerCase().endsWith(".csv")) {
    return cleanLines(await file.text());
  }

  const archive = await JSZip.loadAsync(buffer);
  const parser = new DOMParser();
  const sharedFile = archive.file("xl/sharedStrings.xml");
  const sharedStrings = sharedFile
    ? Array.from(
        parser.parseFromString(await sharedFile.async("text"), "application/xml")
          .getElementsByTagName("si")
      ).map((node) => Array.from(node.getElementsByTagName("t"))
        .map((item) => item.textContent || "")
        .join(""))
    : [];

  const sheetFile = archive.file("xl/worksheets/sheet1.xml");
  if (!sheetFile) return "";
  const document = parser.parseFromString(await sheetFile.async("text"), "application/xml");
  const lines = Array.from(document.getElementsByTagName("row"))
    .map((row) => Array.from(row.getElementsByTagName("c"))
      .map((cell) => {
        const type = cell.getAttribute("t");
        const inlineText = Array.from(cell.getElementsByTagName("t"))
          .map((node) => node.textContent || "")
          .join("");
        const raw = cell.getElementsByTagName("v")[0]?.textContent || inlineText;
        return type === "s" ? sharedStrings[Number(raw)] || "" : raw;
      })
      .map((value) => String(value).trim())
      .filter(Boolean)
      .join(" - "))
    .filter(Boolean);

  return lines.join("\n");

}


export async function extractFromWord(file) {

  const { default: mammoth } = await import("mammoth");
  const buffer = await file.arrayBuffer();

  const { value } = await mammoth.extractRawText({
    arrayBuffer: buffer
  });

  return cleanLines(value);

}


export async function extractFromPdf(file) {

  const [pdfjsLib, workerModule] = await Promise.all([
    import("pdfjs-dist"),
    import("pdfjs-dist/build/pdf.worker.min.mjs?url"),
  ]);
  pdfjsLib.GlobalWorkerOptions.workerSrc = workerModule.default;
  const buffer = await file.arrayBuffer();

  const pdf = await pdfjsLib.getDocument({
    data: buffer
  }).promise;

  const pageLines = [];

  for (let pageNumber = 1; pageNumber <= pdf.numPages; pageNumber++) {

    const page = await pdf.getPage(pageNumber);
    const content = await page.getTextContent();

    const pageText = content.items
      .map((item) => item.str)
      .join(" ");

    pageLines.push(pageText);

  }

  return cleanLines(pageLines.join("\n"));

}


export async function extractFromImage(file, onProgress) {

  const { createWorker } = await import("tesseract.js");
  const worker = await createWorker(
    "ara+eng",
    1,
    {
      logger: (message) => {

        if (
          onProgress &&
          message.status === "recognizing text"
        ) {

          onProgress(
            Math.round(
              (message.progress || 0) * 100
            )
          );

        }

      }
    }
  );

  const { data } = await worker.recognize(file);

  await worker.terminate();

  return cleanLines(data.text);

}


// method: "image" | "pdf" | "excel" | "word"
export async function extractStepsFromFile(method, file, onProgress) {

  switch (method) {

    case "excel":
      return extractFromExcel(file);

    case "word":
      return extractFromWord(file);

    case "pdf":
      return extractFromPdf(file);

    case "image":
      return extractFromImage(file, onProgress);

    default:
      return "";

  }

}
