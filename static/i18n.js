/* Local UI language, deliberately separate from recording and content language. */
(function(root) {
  "use strict";
  function choose(query, saved, browserLanguage) {
    for (const candidate of [query, saved]) if (["zh", "en"].includes(candidate)) return candidate;
    return /^zh\b/i.test(browserLanguage || "") ? "zh" : "en";
  }
  function format(message, values) {
    // A callback keeps dollar signs/braces inside user text literal.
    return message.replace(/\{(\d+)\}/g, (match, index) => index < values.length ? String(values[index] ?? "") : match);
  }
  function translator(messages, language, copy = {}) {
    const t = (key, ...values) => typeof key === "string" ? format(copy[key]?.[language] ?? (language === "en" ? (messages[key] ?? key) : key), values) : (key ?? "");
    const tt = (parts, ...values) => t(parts.map((part,index) => part+(index<parts.length-1 ? `{${index}}` : "")).join(""), ...values);
    return {t, tt};
  }
  function diagnostics(messages, language, copy = {}) {
    const hasHan = value => /\p{Script=Han}/u.test(value);
    const escape = value => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const templates = Object.entries(messages).filter(([key])=>/\{\d+\}/.test(key)).map(([key, translated])=>{
      const indexes=[], parts=[]; let start=0;
      for (const match of key.matchAll(/\{(\d+)\}/g)) {
        parts.push(escape(key.slice(start,match.index)),"([\\s\\S]+?)"); indexes.push(Number(match[1])); start=match.index+match[0].length;
      }
      parts.push(escape(key.slice(start)));
      return {pattern:new RegExp("^"+parts.join("")+"$"),indexes,translated,strategy:key==="{0}：尝试 {1}/4 · {2}"};
    });
    function info(value) {
      const original = String(value ?? "");
      if (Object.hasOwn(copy,original)) return {message:copy[original][language],original:null};
      if (!original || language!=="en" || !hasHan(original)) return {message:original,original:null};
      if (Object.hasOwn(messages,original)) return {message:messages[original],original:null};
      for (const rule of templates) {
        const match=original.match(rule.pattern);
        if (!match) continue;
        const values=[]; rule.indexes.forEach((index,i)=>{values[index]=rule.strategy && index===2 ? messages[match[i+1]] ?? match[i+1] : match[i+1];});
        return {message:format(rule.translated,values),original:null};
      }
      return {message:"A system error or warning was reported. Open the original diagnostic for details.",original};
    }
    function sourceText(segment, value=segment.text) {
      // Only a recognized system marker with ASR metadata is UI text. Never
      // translate arbitrary transcript text, user edits, filenames or notes.
      if (language!=="en" || !(segment.asr_issue || segment.repair_method) || typeof value!=="string") return value;
      const match=value.match(/^【转写缺口，非录音原文】此处本地识别异常：([\s\S]+)。请回听或另行补转；没有保留疑似循环输出。$/);
      if (!match) return value;
      const reasons=match[1].split("；").map(reason=>info(reason).message).join("; ");
      return "[Transcription gap — system marker, not recorded speech] Local recognition issue: "+reasons+". Listen or retry this passage; rejected output was not saved as speech.";
    }
    return {info,diagnostic:value=>info(value).message,sourceText};
  }
  const pure = {choose, format, translator, diagnostics};
  if (typeof module !== "undefined" && module.exports) { module.exports=pure; return; }
  let saved="";
  try { saved=root.localStorage.getItem("lecture-atelier.ui-language") || ""; } catch (_) { /* URL preference still works. */ }
  const current=new URL(root.location.href);
  const language=choose(current.searchParams.get("ui"),saved,root.navigator.language);
  const {t,tt}=translator(root.LectureEnglish || {},language,root.LectureUiCopy || {});
  const diagnosticTools=diagnostics(root.LectureEnglish || {},language,root.LectureUiCopy || {});
  function applyStatic(document) {
    document.documentElement.lang=language==="en" ? "en" : "zh-CN";
    document.title=language==="en" ? "Lecture Atelier · Local study workspace" : "听课之间 · Lecture Atelier";
    // Called once BEFORE data is loaded. Never observe/translate later content.
    const walker=document.createTreeWalker(document.body,root.NodeFilter.SHOW_TEXT);
    let node;
    while ((node=walker.nextNode())) {
      if (node.parentElement.closest("script, style, textarea, [data-no-i18n]")) continue;
      const original=node.nodeValue.trim();
      if (original) node.nodeValue=node.nodeValue.replace(original,t(original));
    }
    for (const element of document.querySelectorAll("[placeholder], [aria-label], [title]")) {
      for (const attribute of ["placeholder","aria-label","title"]) {
        if (element.hasAttribute(attribute)) element.setAttribute(attribute,t(element.getAttribute(attribute)));
      }
    }
    const picker=document.getElementById("ui-language"); if(picker) picker.value=language;
    const help=document.getElementById("help-link"); if(help) help.href=`/help?ui=${language}`;
  }
  function switchTo(next, lectureId) {
    if (!["zh","en"].includes(next)) return;
    try { root.localStorage.setItem("lecture-atelier.ui-language",next); } catch (_) { /* Persist in URL when browser storage is blocked. */ }
    const url=new URL(root.location.href); url.searchParams.set("ui",next);
    if (lectureId) url.hash=`lecture=${encodeURIComponent(lectureId)}`;
    root.location.replace(url.href);
  }
  function renderDiagnostic(target, value) {
    const previous=target.querySelector(".diagnostic-original"),expanded=previous && !previous.hidden,previousText=previous?.textContent;
    const values=Array.isArray(value)?value:[value], items=values.map(diagnosticTools.info);
    target.replaceChildren(root.document.createTextNode(items.map(row=>row.message).join("; ")));
    const originals=items.flatMap(row=>row.original?[row.original]:[]);
    if (originals.length) {
      const control=root.document.createElement("button"), detail=root.document.createElement("span");
      control.type="button"; control.className="text-button diagnostic-toggle";
      detail.className="diagnostic-original"; detail.textContent="\n"+originals.join("\n");
      detail.hidden=!(expanded && previousText===detail.textContent);
      control.textContent=detail.hidden?"Show original diagnostic":"Hide original diagnostic"; control.setAttribute("aria-expanded",String(!detail.hidden));
      control.addEventListener("click",()=>{detail.hidden=!detail.hidden;control.textContent=detail.hidden?"Show original diagnostic":"Hide original diagnostic";control.setAttribute("aria-expanded",String(!detail.hidden));});
      target.append(root.document.createTextNode(" "),control,detail);
    }
  }
  const uiCopy=(zh,en)=>(root.LectureUiCopy||{})[zh]?.[language] ?? (language==="en"?en:zh);
  root.LectureI18n={language,locale:language==="en" ? "en-GB" : "zh-CN",t,tt,uiCopy,applyStatic,switchTo,...diagnosticTools,renderDiagnostic};
  applyStatic(root.document);
})(typeof window === "undefined" ? {} : window);
