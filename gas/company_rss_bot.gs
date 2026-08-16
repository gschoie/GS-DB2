/**
 * 조선/방산 기업 뉴스 모니터 (매경·한경 RSS + 연합·더구루 HTML) → 텔레그램
 * Apps Script 프로젝트: "매경,한경, 연합, 더구루 | 기업 RSS.읽어오기" / 트리거: runOnce (10분)
 *
 * 정본은 이 파일(gas/company_rss_bot.gs). 수정 시 Apps Script 편집기에 전체를
 * 붙여넣으면 끝 — 트리거 실행이라 dispatch_proxy와 달리 '배포'가 필요 없다.
 *
 * 필수 Script Properties (코드에 토큰을 하드코딩하지 말 것 — 이 파일은 공개 리포에 있다):
 * - TELEGRAM_BOT_TOKEN
 * - TELEGRAM_CHAT_ID
 * 선택:
 * - SEND_EXISTING_ON_FIRST_RUN=true
 * - LOOKBACK_HOURS=30
 *
 * 2026-08-16 '6분 실행한도 초과' 재발 방지 개정:
 * - 소스 순차 fetch → UrlFetchApp.fetchAll 병렬 (전체 대기 = 가장 느린 소스 1개)
 * - HTML 링크 추출에 크기·횟수 상한 (정규식 폭주 방지)
 * - LockService로 겹침 실행 차단 (10분 트리거 + 느린 run 조합 대비)
 * - '본 기사' 저장을 텔레그램 전송 성공 뒤로 이동 (중간에 죽어도 기사 유실 없음)
 */

const CONFIG = {
  timezone: "Asia/Seoul",
  lookbackHours: Number(getProp_("LOOKBACK_HOURS", "30")),
  maxSeen: 1200,
  maxItemsPerRun: 20,
  sendExistingOnFirstRun: getProp_("SEND_EXISTING_ON_FIRST_RUN", "false") === "true",
  htmlMaxChars: 400000, // 목록 페이지는 상단만 봐도 충분 — 비정상적으로 큰 응답의 정규식 비용 차단
  maxAnchorScan: 3000, // 페이지당 앵커 스캔 상한
  maxLinksPerSource: 300,
};

const RSS_SOURCES = [
  {
    name: "매일경제 기업·경영",
    url: "https://www.mk.co.kr/rss/50100032/",
    sourceWeight: 1,
  },
  {
    name: "매일경제 경제",
    url: "https://www.mk.co.kr/rss/30100041/",
    sourceWeight: 0,
  },
  {
    name: "한국경제 경제",
    url: "https://www.hankyung.com/feed/economy",
    sourceWeight: 1,
  },
  {
    name: "한국경제 전체뉴스",
    url: "https://www.hankyung.com/feed/all-news",
    sourceWeight: 0,
  },
];

// RSS가 없는 매체/섹션은 이 배열에 URL을 추가해 보조 수집합니다.
// 언론사 개편에 취약하므로, 처음에는 RSS 중심으로 운영하고 필요한 것만 켜세요.
const HTML_SOURCES = [
  {
    name: "연합뉴스 산업",
    url: "https://www.yna.co.kr/industry/all",
    baseUrl: "https://www.yna.co.kr",
    sourceWeight: 2,
  },
  {
    name: "더구루",
    url: "https://www.theguru.co.kr/news/articleList.html",
    baseUrl: "https://www.theguru.co.kr",
    sourceWeight: 1,
  },
];

const COMPANY_KEYWORDS = [
  "MASGA",
  "FDC",
  "MAP",
  "FLNG",
  "존스액트",

  "HD한국조선해양",
  "HD현대중공업",
  "현대중공업",
  "삼성중공업",
  "한화오션",

  "한화엔진",
  "HD현대마린",
  "HD현대마린엔진",
  "HD현대마린솔루션",

  "세진중공업",
  "한국카본",

  "한화에어로스페이스",
  "한화시스템",
  "LIG",
  "한국항공우주",
  "KAI",
  "현대로템",

  "풍산",
  "SNT다이내믹스",
  "삼양컴텍",
  "엠앤씨솔루션",

  "HD건설기계",
  "밥캣",
];

function runOnce() {
  // 이전 회차가 아직 돌고 있으면 건너뛴다 — 겹침 실행이 STATE_JSON을 서로 덮어쓰는 사고 방지.
  const lock = LockService.getScriptLock();
  if (!lock.tryLock(5 * 1000)) {
    Logger.log("이전 실행이 진행 중 — 이번 회차는 건너뜁니다.");
    return;
  }
  try {
    runOnce_();
  } finally {
    lock.releaseLock();
  }
}

function runOnce_() {
  const t0 = Date.now();
  const state = loadState_();
  const firstRun = !state.initialized;

  const items = fetchAllSources_();

  const freshItems = normalizeAndRank_(items)
    .filter((item) => isRecent_(item.publishedAt))
    .filter((item) => !state.seen[item.id])
    .slice(0, CONFIG.maxItemsPerRun);

  if (firstRun && !CONFIG.sendExistingOnFirstRun) {
    freshItems.forEach((item) => {
      state.seen[item.id] = nowIso_();
    });
    markInitializedAndSave_(state);
    sendTelegram_(
      "[조선/방산 뉴스봇]\n초기 실행 완료. 현재 피드는 기준선으로 저장했고, 다음 실행부터 신규 기사만 보냅니다."
    );
    return;
  }

  if (!freshItems.length) {
    markInitializedAndSave_(state);
    Logger.log("No new matching items. (" + (Date.now() - t0) + "ms)");
    return;
  }

  // 전송이 성공한 뒤에만 '본 기사'로 저장한다.
  // 반대 순서였다가 전송 전에 죽으면 그 기사들은 영영 발송되지 않는다.
  sendTelegram_(buildTelegramMessage_(freshItems));
  freshItems.forEach((item) => {
    state.seen[item.id] = nowIso_();
  });
  markInitializedAndSave_(state);
  Logger.log(freshItems.length + "건 전송 (" + (Date.now() - t0) + "ms)");
}

function markInitializedAndSave_(state) {
  pruneSeen_(state);
  state.initialized = true;
  saveState_(state);
}

function createHourlyTrigger() {
  deleteTriggers_();
  ScriptApp.newTrigger("runOnce").timeBased().everyHours(1).create();
}

function deleteTriggers_() {
  ScriptApp.getProjectTriggers().forEach((trigger) => {
    if (trigger.getHandlerFunction() === "runOnce") {
      ScriptApp.deleteTrigger(trigger);
    }
  });
}

function deleteAllProjectTriggers() {
  ScriptApp.getProjectTriggers().forEach((trigger) => {
    ScriptApp.deleteTrigger(trigger);
  });
}

function testTelegram() {
  sendTelegram_("[조선/방산 뉴스봇]\n텔레그램 연결 테스트입니다.");
}

/**
 * 모든 소스를 fetchAll로 병렬 수집한다.
 * 순차 fetch는 느린 소스 하나가 전체를 지연시켜 '6분 실행한도 초과'의 주원인이었다.
 */
function fetchAllSources_() {
  const sources = RSS_SOURCES.map((s) => Object.assign({ kind: "rss" }, s)).concat(
    HTML_SOURCES.map((s) => Object.assign({ kind: "html" }, s))
  );
  const requests = sources.map((s) => ({
    url: s.url,
    muteHttpExceptions: true,
    followRedirects: true,
    headers: { "User-Agent": "Mozilla/5.0 (compatible; GAS news monitor)" },
  }));

  let responses;
  try {
    responses = UrlFetchApp.fetchAll(requests);
  } catch (error) {
    Logger.log("fetchAll failed: " + error);
    return [];
  }

  const items = [];
  responses.forEach((response, i) => {
    const source = sources[i];
    try {
      const code = response.getResponseCode();
      if (code < 200 || code >= 300) throw new Error("HTTP " + code);
      const text = response.getContentText();
      if (source.kind === "rss") {
        parseFeed_(text).forEach((item) => {
          item.source = source.name;
          item.sourceWeight = source.sourceWeight || 0;
          items.push(item);
        });
      } else {
        extractLinks_(text, source.baseUrl || source.url).forEach((link) => {
          items.push({
            title: link.title,
            link: link.url,
            description: "",
            source: source.name,
            sourceWeight: source.sourceWeight || 0,
            publishedAt: null,
          });
        });
      }
    } catch (error) {
      Logger.log("source failed: " + source.name + " / " + error);
    }
  });
  return items;
}

function parseFeed_(xmlText) {
  const doc = XmlService.parse(xmlText);
  const root = doc.getRootElement();
  const rootName = root.getName().toLowerCase();

  if (rootName === "rss" || rootName === "rdf") {
    const channel = firstChild_(root, "channel") || root;
    return channel.getChildren("item").map((item) => ({
      title: childText_(item, "title"),
      link: childText_(item, "link"),
      description: childText_(item, "description"),
      publishedAt: parseDate_(childText_(item, "pubDate")),
      id: childText_(item, "guid") || childText_(item, "link") || childText_(item, "title"),
    }));
  }

  if (rootName === "feed") {
    return root.getChildren("entry", root.getNamespace()).map((entry) => ({
      title: childTextAnyNs_(entry, "title"),
      link: atomLink_(entry),
      description: childTextAnyNs_(entry, "summary"),
      publishedAt: parseDate_(childTextAnyNs_(entry, "updated") || childTextAnyNs_(entry, "published")),
      id: childTextAnyNs_(entry, "id") || atomLink_(entry) || childTextAnyNs_(entry, "title"),
    }));
  }

  return [];
}

function normalizeAndRank_(items) {
  const byId = {};

  items.forEach((item) => {
    const title = cleanText_(item.title || "");
    const description = cleanText_(item.description || "");
    const link = item.link || "";
    if (!title || !link) return;

    const id = item.id || stableId_(link || title);
    const matchedCompanies = matchCompanies_(title + " " + description);
    if (!matchedCompanies.length) return;

    byId[id] = {
      id: id,
      title: title,
      link: link,
      description: description,
      source: item.source || "unknown",
      publishedAt: item.publishedAt || null,
      matchedCompanies: matchedCompanies,
      sourceWeight: item.sourceWeight || 0,
    };
  });

  return Object.keys(byId)
    .map((id) => byId[id])
    .sort((a, b) => b.sourceWeight - a.sourceWeight);
}

function matchCompanies_(text) {
  const normalized = text.toLowerCase();
  const matchedCompanies = [];

  COMPANY_KEYWORDS.forEach((company) => {
    if (normalized.indexOf(company.toLowerCase()) !== -1) {
      matchedCompanies.push(company);
    }
  });

  return unique_(matchedCompanies);
}

function buildTelegramMessage_(items) {
  const header =
    "<b>[매/한/연/구 키워드 RSS. 10분]</b>\n" +
    formatDate_(new Date(), "yyyy-MM-dd HH:mm") +
    " KST / 신규 " +
    items.length +
    "건\n";

  const lines = items.map((item, index) => {
    const dateText = item.publishedAt ? formatDate_(item.publishedAt, "MM-dd HH:mm") : "시간미상";
    return (
      "\n" +
      (index + 1) +
      ". " +
      "<b>" +
      escapeTelegramHtml_(item.title) +
      "</b>" +
      "\n" +
      "출처: " +
      escapeTelegramHtml_(item.source) +
      " / " +
      dateText +
      "\n" +
      "회사: " +
      escapeTelegramHtml_(item.matchedCompanies.length ? item.matchedCompanies.join(", ") : "-") +
      "\n" +
      escapeTelegramHtml_(item.link)
    );
  });

  return header + lines.join("\n");
}

function escapeTelegramHtml_(text) {
  return String(text || "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function sendTelegram_(text) {
  const token = getRequiredProp_("TELEGRAM_BOT_TOKEN");
  const chatId = getRequiredProp_("TELEGRAM_CHAT_ID");
  const chunks = chunkText_(text, 3600);

  chunks.forEach((chunk) => {
    const url = "https://api.telegram.org/bot" + token + "/sendMessage";
    const response = UrlFetchApp.fetch(url, {
      method: "post",
      muteHttpExceptions: true,
      payload: {
        chat_id: chatId,
        text: chunk,
        parse_mode: "HTML",
        disable_web_page_preview: "true",
      },
    });
    const code = response.getResponseCode();
    // 전송 실패를 조용히 삼키면 기사가 유실된 채 seen 처리된다 → 실패는 던져서
    // 이번 회차를 실패로 남기고, 다음 회차가 같은 기사를 재시도하게 한다.
    if (code < 200 || code >= 300) {
      throw new Error("Telegram HTTP " + code + ": " + response.getContentText().slice(0, 200));
    }
  });
}

function extractLinks_(html, baseUrl) {
  // 상한 없는 정규식 스캔은 목록 페이지가 비대하거나 마크업이 깨진 날 실행시간을 폭주시킨다.
  let text = String(html || "");
  if (text.length > CONFIG.htmlMaxChars) text = text.slice(0, CONFIG.htmlMaxChars);

  const links = [];
  const anchorRegex = /<a\b[^>]*href=["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi;
  let match;
  let scanned = 0;

  while ((match = anchorRegex.exec(text)) !== null) {
    if (++scanned > CONFIG.maxAnchorScan || links.length >= CONFIG.maxLinksPerSource) break;
    const url = absoluteUrl_(match[1], baseUrl);
    const title = cleanText_(stripTags_(match[2]));
    if (!url || !title || title.length < 8) continue;
    if (url.indexOf("javascript:") === 0 || url.indexOf("#") === 0) continue;
    links.push({ url: url, title: title });
  }

  const seen = {};
  return links.filter((link) => {
    const key = link.url + "|" + link.title;
    if (seen[key]) return false;
    seen[key] = true;
    return true;
  });
}

function isRecent_(date) {
  if (!date) return true;
  const cutoff = new Date().getTime() - CONFIG.lookbackHours * 60 * 60 * 1000;
  return date.getTime() >= cutoff;
}

function loadState_() {
  const props = PropertiesService.getScriptProperties();
  const raw = props.getProperty("STATE_JSON");
  if (!raw) return { initialized: false, seen: {} };
  try {
    const state = JSON.parse(raw);
    state.seen = state.seen || {};
    return state;
  } catch (error) {
    return { initialized: false, seen: {} };
  }
}

function saveState_(state) {
  PropertiesService.getScriptProperties().setProperty("STATE_JSON", JSON.stringify(state));
}

function pruneSeen_(state) {
  const entries = Object.keys(state.seen).map((id) => ({ id: id, time: state.seen[id] }));
  entries.sort((a, b) => String(b.time).localeCompare(String(a.time)));
  state.seen = {};
  entries.slice(0, CONFIG.maxSeen).forEach((entry) => {
    state.seen[entry.id] = entry.time;
  });
}

function childText_(element, name) {
  const child = firstChild_(element, name);
  return child ? child.getText() : "";
}

function childTextAnyNs_(element, name) {
  const children = element.getChildren();
  for (let i = 0; i < children.length; i++) {
    if (children[i].getName() === name) return children[i].getText();
  }
  return "";
}

function firstChild_(element, name) {
  const children = element.getChildren();
  for (let i = 0; i < children.length; i++) {
    if (children[i].getName() === name) return children[i];
  }
  return null;
}

function atomLink_(entry) {
  const links = entry.getChildren("link", entry.getNamespace());
  for (let i = 0; i < links.length; i++) {
    const href = links[i].getAttribute("href");
    if (href) return href.getValue();
  }
  return "";
}

function parseDate_(value) {
  if (!value) return null;
  const text = String(value).trim();
  if (/^\d{8}$/.test(text)) {
    return new Date(
      Number(text.slice(0, 4)),
      Number(text.slice(4, 6)) - 1,
      Number(text.slice(6, 8))
    );
  }
  const parsed = new Date(text);
  return isNaN(parsed.getTime()) ? null : parsed;
}

function cleanText_(text) {
  return String(text || "")
    .replace(/<!\[CDATA\[|\]\]>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

function stripTags_(html) {
  return String(html || "").replace(/<[^>]+>/g, " ");
}

function absoluteUrl_(href, baseUrl) {
  if (!href) return "";
  if (/^https?:\/\//i.test(href)) return href;
  if (href.indexOf("//") === 0) return "https:" + href;

  const originMatch = String(baseUrl).match(/^(https?:\/\/[^/]+)/i);
  const origin = originMatch ? originMatch[1] : "";
  if (href.charAt(0) === "/") return origin + href;

  return String(baseUrl).replace(/\/[^/]*$/, "/") + href;
}

function containsAny_(text, terms) {
  const haystack = String(text || "").toLowerCase();
  return terms.some((term) => haystack.indexOf(String(term).toLowerCase()) !== -1);
}

function unique_(values) {
  const seen = {};
  return values.filter((value) => {
    if (seen[value]) return false;
    seen[value] = true;
    return true;
  });
}

function stableId_(text) {
  const digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256, text);
  return digest
    .map((byte) => {
      const value = byte < 0 ? byte + 256 : byte;
      return ("0" + value.toString(16)).slice(-2);
    })
    .join("");
}

function chunkText_(text, size) {
  const chunks = [];
  for (let i = 0; i < text.length; i += size) {
    chunks.push(text.slice(i, i + size));
  }
  return chunks;
}

function formatDate_(date, pattern) {
  return Utilities.formatDate(date, CONFIG.timezone, pattern);
}

function nowIso_() {
  return Utilities.formatDate(new Date(), "UTC", "yyyy-MM-dd'T'HH:mm:ss'Z'");
}

function getProp_(name, fallback) {
  const value = PropertiesService.getScriptProperties().getProperty(name);
  return value == null || value === "" ? fallback : value;
}

function getRequiredProp_(name) {
  const value = getProp_(name, "");
  if (!value) throw new Error("Missing Script Property: " + name);
  return value;
}
