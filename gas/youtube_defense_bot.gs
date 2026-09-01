// 방산 유튜브 알림 봇 + 3일 모음 (Google Apps Script 정본)
//
// 트리거 두 개로 돈다.
//   checkNewVideos()      — 새 영상 감지 → 제미나이 요약 → 텔레그램 낱개 발송 (자주)
//   sendThreeDayDigest()  — 3일치 링크를 모아 한 번에 발송 (NotebookLM 소스용)
//
// 손으로 한 번씩 돌리는 것들
//   checkSetup()          — 스크립트 속성이 제대로 들어갔는지 확인
//   installDigestTrigger()— 3일 트리거 걸기
//   fillBufferFromFeeds(3)— 지난 3일치를 버퍼에 채워 넣기 (지금 바로 시험해 볼 때)
//
// 3일 모음에는 쇼츠를 담지 않는다(DIGEST_SKIP_SHORTS). 낱개 알림은 쇼츠도 그대로 온다.
//
// 낱개 발송 때 링크를 스크립트 속성에 같이 쌓아 두고, 3일마다 그걸 비워 내보낸다.
// 유튜브를 다시 긁지 않으므로 봇에 실제로 나간 것과 100% 일치한다.
//
// 키는 소스에 적지 않는다. 프로젝트 설정 → 스크립트 속성에 아래를 넣을 것.
//   TELEGRAM_TOKEN / TELEGRAM_CHAT_ID / GEMINI_API_KEY
//   GH_TOKEN (선택) — 있으면 3일 모음을 대시보드에도 남긴다. actions:write 권한 필요.
// 넣고 나서 checkSetup() 을 한 번 돌리면 제대로 들어갔는지 확인된다.

const PROPS = PropertiesService.getScriptProperties();

// 3일 모음 버퍼가 쓰는 속성 키 앞머리. LAST_VIDEO_ 와 섞이지 않는다.
const DIGEST_PREFIX = 'DIGEST_';

// 마지막 모음 발송 시각(밀리초). 자동 트리거는 이걸 보고 3일이 안 찼으면 건너뛴다.
// 수동 갱신도 발송이므로 여기 찍힌다 — 즉 수동으로 뽑으면 그때부터 다시 3일을 센다.
const LAST_DIGEST_KEY = 'LAST_DIGEST_AT';

// 모음을 대시보드에도 남길 곳 (GS-DB2 의 '유튜브 3일 모음' 워크플로).
const DASHBOARD_OWNER = 'gschoie';
const DASHBOARD_REPO = 'GS-DB2';
const DASHBOARD_WORKFLOW = 'youtube-digest.yml';
const DASHBOARD_REF = 'main';

// 기록해 둔 영상이 피드에서 사라졌을 때(삭제·비공개) 피드 전체를 쏟아내지 않기 위한 상한.
const MAX_NEW_PER_RUN = 5;

// 3일 모음에서 쇼츠를 뺀다. 쇼츠는 자막이 거의 없어 NotebookLM이 소스로 받지 못하고,
// 무료 플랜 소스 상한(50개)만 잡아먹는다. 낱개 알림에는 영향이 없다 — 쇼츠도 그대로 온다.
// 다시 담고 싶으면 이 값을 false 로.
const DIGEST_SKIP_SHORTS = true;

// 구독할 방산 채널 목록 (총 7개 채널)
const WATCH_CHANNELS = [
  { name: '샤를세환', id: 'UCVNAlg66t3JhkzT5JntclLg' },
  { name: 'KKMD', id: 'UCLDV9mI3tOQCrdPUWjogQZA' },
  { name: '까치살모', id: 'UCAhe6Ku_oVhkUTv-VfIus8A' },
  { name: '슈퍼소닉', id: 'UCXK_itQ6_JKltErZW_sQojQ' },
  { name: '밀덕', id: 'UCV-slcYbZrNCowaVd3cQaHQ' },
  { name: 'KFN+', id: 'UCObL9hob3R03QSZU5olJZiQ' },
  { name: 'KFN1', id: 'UCXNMgSZqmfX1_K8Uf4l4sog' }
];


// === 설정 ===

function secret_(name) {
  const value = PROPS.getProperty(name);
  if (!value) {
    throw new Error('스크립트 속성 ' + name + ' 이 비어 있습니다. '
      + '프로젝트 설정 → 스크립트 속성에서 넣어 주세요.');
  }
  return value;
}

// 한 번 돌려 설정이 제대로 들어갔는지 확인한다.
function checkSetup() {
  ['TELEGRAM_TOKEN', 'TELEGRAM_CHAT_ID', 'GEMINI_API_KEY'].forEach(function (name) {
    const value = PROPS.getProperty(name);
    Logger.log(name + ': ' + (value ? '✅ 설정됨 (' + value.length + '자)' : '❌ 비어 있음'));
  });
  const buffered = digestKeys_().length;
  Logger.log('3일 모음 버퍼: ' + buffered + '건');
  const last = Number(PROPS.getProperty(LAST_DIGEST_KEY) || 0);
  Logger.log('마지막 모음 발송: ' + (last ? new Date(last) : '기록 없음 — 다음 아침 트리거 때 발송'));
  Logger.log('GH_TOKEN: ' + (PROPS.getProperty('GH_TOKEN')
    ? '✅ 설정됨 — 대시보드에도 남깁니다'
    : '— 없음 (텔레그램만 발송. 대시보드에 남기려면 넣으세요)'));
}

// 모음 트리거를 건다. 한 번만 실행하면 된다(여러 번 눌러도 중복되지 않는다).
// 트리거 자체는 매일 아침 돌고, 실제 발송 여부는 scheduledDigest 가 마지막 발송
// 시각으로 판단한다 — 그래야 수동 갱신 뒤 다음 자동 발송이 정확히 3일 뒤가 된다.
// (GAS의 everyDays(3)는 기준점을 못 옮긴다)
function installDigestTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (trigger) {
    const handler = trigger.getHandlerFunction();
    if (handler === 'sendThreeDayDigest' || handler === 'scheduledDigest') {
      ScriptApp.deleteTrigger(trigger);
    }
  });
  ScriptApp.newTrigger('scheduledDigest').timeBased().everyDays(1).atHour(7).create();
  Logger.log('매일 오전 7시에 확인해서, 마지막 발송에서 3일이 지났을 때만 모음을 보냅니다.');
}

// 자동 트리거 전용 — 마지막 발송(수동 포함)에서 3일이 안 지났으면 조용히 넘어간다.
function scheduledDigest() {
  const last = Number(PROPS.getProperty(LAST_DIGEST_KEY) || 0);
  const threeDays = 3 * 24 * 3600 * 1000;
  const grace = 6 * 3600 * 1000;  // 트리거 시각이 조금 일찍 와도 하루를 통째로 밀리지 않게
  if (last > 0 && Date.now() - last < threeDays - grace) {
    Logger.log('마지막 발송 ' + new Date(last) + ' — 3일이 안 지나 건너뜁니다.');
    return;
  }
  sendThreeDayDigest();
}


// === 메인 실행 함수 (HTML 파싱 및 특수문자 에러 방지 버전) ===

function checkNewVideos() {
  WATCH_CHANNELS.forEach(channel => {
    try {
      // 1. 유튜브 RSS 피드를 통해 최근 영상 목록 가져오기
      const url = `https://www.youtube.com/feeds/videos.xml?channel_id=${channel.id}`;
      const response = UrlFetchApp.fetch(url);
      const xml = XmlService.parse(response.getContentText());
      const root = xml.getRootElement();
      const atom = XmlService.getNamespace('http://www.w3.org/2005/Atom');
      const media = XmlService.getNamespace('media', 'http://search.yahoo.com/mrss/');

      const entries = root.getChildren('entry', atom);
      if (entries.length === 0) return;

      // 이전에 마지막으로 알림을 보냈던 영상 ID 가져오기
      const lastSentKey = `LAST_VIDEO_${channel.id}`;
      let lastSentId = PROPS.getProperty(lastSentKey);

      // 피드 상 가장 최신 영상 ID
      const currentNewestId = entries[0].getChildText('id', atom).replace('yt:video:', '');

      // 저장된 기록이 전혀 없거나, 기록이 현재 최신 ID와 같다면 패스하고 기록 확실히 갱신
      if (!lastSentId) {
        PROPS.setProperty(lastSentKey, currentNewestId);
        Logger.log(`${channel.name} 채널 최초 감지 상태 저장 완료 (다음 새 영상부터 알림)`);
        return;
      }

      if (lastSentId === currentNewestId) {
        Logger.log(`${channel.name} 채널은 새로운 영상이 없습니다.`);
        return;
      }

      // 새로 올라온 영상들을 담을 저장소
      let newVideos = [];
      let matched = false;

      // 2. 피드 목록을 확인하며 새 영상 판별
      for (let i = 0; i < entries.length; i++) {
        const entry = entries[i];
        const videoId = entry.getChildText('id', atom).replace('yt:video:', '');

        // 과거에 이미 보낸 영상을 만나면 루프 중단
        if (videoId === lastSentId) {
          matched = true;
          break;
        }

        // 보낸 적 없는 새 영상이라면 배열에 보관
        newVideos.push(entry);
      }

      // 기록해 둔 영상이 피드에 없다(삭제·비공개·15개 초과 업로드).
      // 그대로 두면 피드 전체가 한꺼번에 나가고 제미나이도 그만큼 호출된다.
      if (!matched && newVideos.length > MAX_NEW_PER_RUN) {
        Logger.log(`${channel.name}: 기록(${lastSentId})이 피드에 없어 `
          + `${newVideos.length}건 중 최신 ${MAX_NEW_PER_RUN}건만 보냅니다.`);
        newVideos = newVideos.slice(0, MAX_NEW_PER_RUN);
      }

      // 3. 새 영상이 존재한다면 한꺼번에 발송 처리
      if (newVideos.length > 0) {
        // 먼저 올라온 영상 순서대로 보이기 위해 뒤집기
        newVideos.reverse();

        newVideos.forEach(entry => {
          const videoId = entry.getChildText('id', atom).replace('yt:video:', '');
          let videoTitle = entry.getChildText('title', atom);
          const videoUrl = entry.getChild('link', atom).getAttribute('href').getValue();

          const mediaGroup = entry.getChild('group', media);
          let description = '';
          if (mediaGroup) {
            description = mediaGroup.getChildText('description', media);
          }

          // 제미나이 AI 요약 생성
          let aiSummary = '';
          if (description.trim().length > 10) {
            aiSummary = askGeminiSummary_(videoTitle, description);
          } else {
            aiSummary = '영상 설명이 비어있습니다.';
          }

          // 3일 모음 버퍼에 적립 — 발송 전에 넣어 둔다.
          // 텔레그램 전송이 실패해도 링크는 남아 다음 모음에 실린다.
          const publishedAt = new Date(entry.getChildText('published', atom)).getTime();
          bufferForDigest_(channel.name, videoId, videoTitle, videoUrl, publishedAt);

          // HTML 특수문자 충돌 방지를 위한 안전치환 (< 와 > 부품 보호)
          const safeTitle = escapeHtml_(videoTitle);
          const safeSummary = escapeHtml_(aiSummary);

          // 텔레그램 메시지 조립 — 쇼츠는 머리말로 구분한다
          const header = isShorts_(videoUrl)
            ? `🎬 <b>새로운 방산 쇼츠 업로드!</b>`
            : `📺 <b>새로운 방산 영상 업로드!</b>`;
          const message =
            header + `\n\n` +
            `• <b>채널:</b> ${channel.name}\n` +
            `• <b>제목:</b> <b>${safeTitle}</b>\n\n` +
            `• <b>제미나이 AI 핵심 요약:</b>\n${safeSummary}\n\n` +
            `🔗 <b>바로가기:</b> ${videoUrl}`;

          // 텔레그램 전송
          sendTelegramMessage_(message);
          Logger.log(`알림 발송 완료 (${channel.name}): ${videoTitle}`);
        });

        // 4. 발송 완료 후 기록 갱신 및 안전 대기시간 부여
        PROPS.setProperty(lastSentKey, currentNewestId);
        Utilities.sleep(500);
      }

    } catch (error) {
      Logger.log(`에러 발생 (${channel.name}): ${error.toString()}`);
    }
  });
}


// === 3일 모음 — NotebookLM 소스용 ===
//
// 낱개 알림을 보낼 때마다 여기 한 건씩 쌓인다. 속성 하나에 영상 하나씩 넣는 이유는
// 스크립트 속성이 값 하나당 9KB 제한이 있어서다 — JSON 배열 하나로 모으면 언젠가 터진다.

function digestKeys_() {
  const all = PROPS.getProperties();
  return Object.keys(all)
    .filter(function (key) { return key.indexOf(DIGEST_PREFIX) === 0; })
    .sort();  // 키 앞머리가 시각이라 정렬하면 올라온 순서가 된다
}

// 유튜브 피드는 쇼츠를 .../shorts/<id> 주소로 준다. 확실한 판별법은 이것뿐이라
// 최선의 추정이다 — 피드가 쇼츠를 watch?v= 로 주면 걸러지지 않는다.
function isShorts_(url) {
  return String(url).indexOf('/shorts/') !== -1;
}

// /shorts/<id> → watch?v=<id>. 같은 영상이고, NotebookLM·브라우저 모두 이 형태를 받는다.
function normalizeVideoUrl_(url) {
  const found = String(url).match(/\/shorts\/([A-Za-z0-9_-]+)/);
  return found ? 'https://www.youtube.com/watch?v=' + found[1] : url;
}

// 담았으면 true, 쇼츠라 건너뛰었으면 false.
function bufferForDigest_(channelName, videoId, title, url, whenMillis) {
  if (DIGEST_SKIP_SHORTS && isShorts_(url)) return false;
  // 키 앞머리를 '올라온 시각'으로 두면 정렬만으로 업로드 순서가 나온다.
  // 같은 밀리초에 두 건이 들어와도 videoId 가 붙어 있어 덮어쓰이지 않는다.
  const when = whenMillis ? whenMillis : Date.now();
  const key = DIGEST_PREFIX + when + '_' + videoId;
  PROPS.setProperty(key, JSON.stringify({
    ch: channelName, t: title, u: normalizeVideoUrl_(url)
  }));
  return true;
}

function isBuffered_(videoId) {
  const suffix = '_' + videoId;
  return digestKeys_().some(function (key) {
    return key.length > suffix.length
      && key.indexOf(suffix, key.length - suffix.length) !== -1;
  });
}

// 지금 당장 모음을 확인하고 싶을 때. 각 채널 피드에서 최근 days일치를 버퍼에 담는다.
// 낱개 알림은 보내지 않고 LAST_VIDEO_ 기록도 건드리지 않으므로, 평소 동작에 영향이 없다.
// 처음 켤 때 지난 3일치를 채워 넣는 용도로도 쓴다.
function fillBufferFromFeeds(days) {
  const span = (days ? days : 3) * 24 * 60 * 60 * 1000;
  const since = Date.now() - span;
  let added = 0;
  let skipped = 0;

  WATCH_CHANNELS.forEach(function (channel) {
    try {
      const url = 'https://www.youtube.com/feeds/videos.xml?channel_id=' + channel.id;
      const xml = XmlService.parse(UrlFetchApp.fetch(url).getContentText());
      const atom = XmlService.getNamespace('http://www.w3.org/2005/Atom');
      const entries = xml.getRootElement().getChildren('entry', atom);

      entries.forEach(function (entry) {
        const published = new Date(entry.getChildText('published', atom)).getTime();
        if (!published || published < since) return;

        const videoId = entry.getChildText('id', atom).replace('yt:video:', '');
        if (isBuffered_(videoId)) return;

        const title = entry.getChildText('title', atom);
        const link = entry.getChild('link', atom).getAttribute('href').getValue();
        if (bufferForDigest_(channel.name, videoId, title, link, published)) {
          added++;
        } else {
          skipped++;
        }
      });
    } catch (error) {
      Logger.log('버퍼 채우기 실패 (' + channel.name + '): ' + error.toString());
    }
  });

  Logger.log(added + '건을 버퍼에 담았습니다'
    + (skipped ? ' (쇼츠 ' + skipped + '건 제외)' : '')
    + '. 이제 sendThreeDayDigest() 를 돌려 보세요.');
}

function sendThreeDayDigest() {
  const keys = digestKeys_();
  if (keys.length === 0) {
    Logger.log('3일 모음: 쌓인 영상이 없어 보내지 않습니다.');
    return;
  }

  const all = PROPS.getProperties();
  const rows = [];
  keys.forEach(function (key) {
    try {
      const row = JSON.parse(all[key]);
      // 키가 DIGEST_<밀리초>_<영상ID> 라 앞머리에서 올라온 시각을 되찾을 수 있다.
      const millis = Number(key.split('_')[1]);
      if (millis) row.p = new Date(millis).toISOString();
      rows.push(row);
    } catch (e) {
      Logger.log('3일 모음: 못 읽는 항목 하나를 건너뜁니다 — ' + key);
    }
  });
  // 담는 길목에서 이미 거르지만, 예전 코드가 담아 둔 쇼츠가 버퍼에 남아 있을 수
  // 있어 보내는 길목에서도 한 번 더 거른다.
  const kept = DIGEST_SKIP_SHORTS
    ? rows.filter(function (row) { return !isShorts_(row.u); })
    : rows;
  if (kept.length < rows.length) {
    Logger.log('버퍼에 남아 있던 쇼츠 ' + (rows.length - kept.length) + '건을 버립니다.');
  }

  if (kept.length === 0) {
    keys.forEach(function (key) { PROPS.deleteProperty(key); });
    Logger.log('걸러내고 나니 보낼 영상이 없습니다.');
    return;
  }

  // 채널 순서는 WATCH_CHANNELS 순서를 따른다
  const order = {};
  WATCH_CHANNELS.forEach(function (channel, index) { order[channel.name] = index; });

  const byChannel = {};
  kept.forEach(function (row) {
    const name = row.ch || '(채널 미상)';
    if (!byChannel[name]) byChannel[name] = [];
    byChannel[name].push(row);
  });
  const names = Object.keys(byChannel).sort(function (a, b) {
    const ra = (a in order) ? order[a] : 99;
    const rb = (b in order) ? order[b] : 99;
    return ra - rb;
  });

  // 1) 읽는 판 — 채널별 제목
  const stamp = Utilities.formatDate(new Date(), 'Asia/Seoul', 'M월 d일');
  let lines = [
    `📻 <b>3일 모음 · ${stamp}</b>`,
    `채널 ${names.length}개 · 영상 ${kept.length}건`,
    ''
  ];
  names.forEach(function (name) {
    lines.push('<b>' + escapeHtml_(name) + '</b>');
    byChannel[name].forEach(function (row) {
      lines.push('• ' + escapeHtml_(row.t || ''));
    });
    lines.push('');
  });
  lines.push('↓ 다음 메시지를 통째로 복사해 NotebookLM 소스에 붙여넣으세요');
  sendChunked_(lines, false);

  // 2) 붙여넣는 판 — 채널 이름 한 줄 밑에 그 채널 주소들. NotebookLM은 붙여넣은
  // 글에서 유튜브 주소만 골라 읽으므로 채널 이름 줄이 섞여 있어도 문제없다.
  const urls = [];
  names.forEach(function (name) {
    urls.push('[' + name + ']');
    byChannel[name].forEach(function (row) {
      if (row.u) urls.push(row.u);
    });
    urls.push('');
  });
  sendChunked_(urls, true);

  // 대시보드에도 남긴다. 실패해도 텔레그램은 이미 나갔으므로 버퍼를 붙들지 않는다.
  try {
    pushDigestToDashboard_(names, byChannel, kept);
  } catch (error) {
    Logger.log('대시보드 전달 실패 (텔레그램은 정상 발송됨): ' + error.toString());
  }

  // 보낸 뒤에만 비운다. 위에서 예외가 나면 버퍼가 남아 다음 회차에 다시 실린다.
  keys.forEach(function (key) { PROPS.deleteProperty(key); });
  PROPS.setProperty(LAST_DIGEST_KEY, String(Date.now()));
  Logger.log('3일 모음 발송 완료 — 채널 ' + names.length + '개 · 영상 ' + kept.length + '건');
}

// 모음을 GS-DB2 의 워크플로로 넘겨 대시보드 페이지를 만들게 한다.
// GH_TOKEN 이 없으면 조용히 건너뛴다 — 텔레그램만 쓰는 것도 정상 운용이다.
function pushDigestToDashboard_(names, byChannel, rows) {
  const token = PROPS.getProperty('GH_TOKEN');
  if (!token) {
    Logger.log('GH_TOKEN 이 없어 대시보드에는 남기지 않습니다.');
    return;
  }

  const day = function (value) {
    return Utilities.formatDate(new Date(value), 'Asia/Seoul', 'yyyy-MM-dd');
  };
  let earliest = null;
  rows.forEach(function (row) {
    if (!row.p) return;
    const when = new Date(row.p).getTime();
    if (earliest === null || when < earliest) earliest = when;
  });

  const payload = {
    date: day(Date.now()),
    from: earliest ? day(earliest) : '',
    channels: names.map(function (name) {
      return {
        name: name,
        videos: byChannel[name].map(function (row) {
          return { t: row.t || '', u: row.u || '', p: row.p || '' };
        })
      };
    })
  };

  const url = 'https://api.github.com/repos/' + DASHBOARD_OWNER + '/' + DASHBOARD_REPO
    + '/actions/workflows/' + DASHBOARD_WORKFLOW + '/dispatches';
  const response = UrlFetchApp.fetch(url, {
    method: 'post',
    contentType: 'application/json',
    headers: {
      Authorization: 'Bearer ' + token,
      Accept: 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28'
    },
    payload: JSON.stringify({
      ref: DASHBOARD_REF,
      inputs: { payload: JSON.stringify(payload) }
    }),
    muteHttpExceptions: true
  });

  const code = response.getResponseCode();
  // workflow_dispatch 성공은 204 No Content 다.
  if (code === 204) {
    Logger.log('대시보드 워크플로를 깨웠습니다 (영상 ' + rows.length + '건).');
  } else {
    Logger.log('대시보드 전달 실패 HTTP ' + code + ': ' + response.getContentText());
  }
}

// 텔레그램 한 통 4096자 제한 — 줄 단위로 끊어 보낸다.
function sendChunked_(lines, plain) {
  let buffer = [];
  let size = 0;
  lines.forEach(function (line) {
    if (buffer.length > 0 && size + line.length + 1 > 3500) {
      sendTelegramMessage_(buffer.join('\n'), { plain: plain, noPreview: true });
      Utilities.sleep(1100);
      buffer = [];
      size = 0;
    }
    buffer.push(line);
    size += line.length + 1;
  });
  if (buffer.length > 0) {
    sendTelegramMessage_(buffer.join('\n'), { plain: plain, noPreview: true });
  }
}


// === 대시보드 수동 갱신 (웹 앱) ===
//
// 대시보드의 '🔄 모음 갱신' 버튼이 이 프로젝트의 웹앱 주소를 POST {action:'send_digest'}
// 로 부른다. 최근 3일치를 피드에서 다시 채워 즉시 발송한다(텔레그램 + 대시보드).
//
// 설치(1회): 배포 → 새 배포 → 유형 '웹 앱' → 실행 계정 '나' → 액세스 '모든 사용자'
// → 배포. 나온 /exec 주소를 대시보드 app.js 의 YTDIGEST_ENDPOINT 에 넣는다.
// 이후 코드가 바뀌면 '배포 관리 → 새 버전'으로만 갱신할 것 (새 배포 금지 — 주소가 바뀐다).

function doPost(e) {
  const out = { ok: false };
  try {
    let body = {};
    try {
      body = JSON.parse((e && e.postData && e.postData.contents) || '{}');
    } catch (ignored) {}
    if (body.action !== 'send_digest') {
      out.error = 'unknown action';
      return jsonOut_(out);
    }

    // 더블클릭·자동 트리거와의 동시 실행 방지
    const lock = LockService.getScriptLock();
    if (!lock.tryLock(5000)) {
      out.error = '이미 실행 중입니다 — 잠시 뒤 다시 눌러 주세요';
      return jsonOut_(out);
    }
    try {
      fillBufferFromFeeds(3);
      const count = digestKeys_().length;   // 발송하면 버퍼가 비워지므로 먼저 센다
      if (count > 0) sendThreeDayDigest();
      out.ok = true;
      out.videos = count;
    } finally {
      lock.releaseLock();
    }
  } catch (error) {
    out.error = String(error);
  }
  return jsonOut_(out);
}

function jsonOut_(payload) {
  return ContentService.createTextOutput(JSON.stringify(payload))
    .setMimeType(ContentService.MimeType.JSON);
}


// === 제미나이 API 호출 및 요약 함수 ===

function askGeminiSummary_(title, text) {
  try {
    const url = 'https://generativelanguage.googleapis.com/v1beta/models/'
      + 'gemini-2.5-flash:generateContent?key=' + secret_('GEMINI_API_KEY');

    const prompt = `너는 밀리터리, 방위산업 전문 뉴스 요약가야. 유튜브 영상의 제목과 상세 설명을 바탕으로 핵심 내용을 요약해줘.\n\n` +
                   `[영상 제목]: ${title}\n` +
                   `[영상 상세설명]: ${text}\n\n` +
                   `위 내용을 바탕으로 가독성이 좋게 이모지(•)를 사용한 2~3줄의 문장으로 한국어로 요약해줘. 인사말이나 다른 군더더기 말은 다 빼고 오직 요약 내용만 출력해줘.`;

    const payload = {
      "contents": [{
        "parts": [{ "text": prompt }]
      }]
    };

    const options = {
      "method": "post",
      "contentType": "application/json",
      "payload": JSON.stringify(payload),
      "muteHttpExceptions": true
    };

    const response = UrlFetchApp.fetch(url, options);
    const json = JSON.parse(response.getContentText());

    if (json.candidates && json.candidates[0].content && json.candidates[0].content.parts) {
      return json.candidates[0].content.parts[0].text.trim();
    } else {
      return "⚠️ AI 요약 생성 중 오류가 발생했습니다.";
    }
  } catch (e) {
    return "⚠️ 제미나이 API 연결 실패: " + e.toString();
  }
}


// === 텔레그램 메시지 전송 함수 ===
//
// opts.plain    : true 면 HTML 파싱을 끈다 (주소만 보낼 때 — 태그로 오해받을 일이 없다)
// opts.noPreview: true 면 링크 미리보기 카드를 안 만든다 (모음 메시지가 길어지는 걸 막는다)

function sendTelegramMessage_(text, opts) {
  opts = opts || {};
  const url = `https://api.telegram.org/bot${secret_('TELEGRAM_TOKEN')}/sendMessage`;
  const payload = {
    'chat_id': secret_('TELEGRAM_CHAT_ID'),
    'text': text,
    'disable_web_page_preview': opts.noPreview === true
  };
  if (opts.plain !== true) {
    payload['parse_mode'] = 'HTML';
  }

  const options = {
    'method': 'post',
    'contentType': 'application/json',
    'payload': JSON.stringify(payload)
  };

  UrlFetchApp.fetch(url, options);
}


// === HTML 특수문자 무력화 안전 함수 ===

function escapeHtml_(text) {
  return String(text)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}
