'use strict';

// The browser's job is narrow: hold the microphone, ship raw samples, and
// render what the server sends back. All measurement happens server-side.

const el = (id) => document.getElementById(id);

// ------------------------------------------------------------------ language

// The server resolves the language — the configured setting, or the browser's
// own preference under "auto" — and states it on the page, so the text drawn
// here and the messages the server sends always agree.
const LANG = document.documentElement.lang === 'ru' ? 'ru' : 'en';

// Russian needs three forms after a number; English two.
function plural(count, forms) {
  if (LANG !== 'ru') return count === 1 ? forms[0] : forms[1];
  const mod100 = count % 100;
  if (mod100 >= 11 && mod100 <= 14) return forms[2];
  const mod10 = count % 10;
  if (mod10 === 1) return forms[0];
  if (mod10 >= 2 && mod10 <= 4) return forms[1];
  return forms[2];
}

const STRINGS = {
  en: {
    tagline: 'Align your speakers\' delays using your phone\'s microphone',
    popout_text: 'The browser may refuse the microphone to a page inside the Home Assistant panel —',
    popout_link: 'open Speaker Sync Calibrator on its own, without the panel',
    needs_https: 'The browser only gives the microphone to a page opened over https://, and'
      + ' Home Assistant is open over plain http:// now. Open it at its https:// address'
      + ' (Home Assistant Cloud, or your own certificate) and calibration will work.',
    speakers: 'Speakers',
    refresh: 'Refresh',
    loading: 'Loading…',
    switch_note: 'A speaker switched off is left alone: it is not measured, not grouped'
      + ' and its delay is not changed. Useful for a subwoofer, a speaker in another'
      + ' room, or one you set by hand.',
    idle: 'Put the phone where you listen and press “Calibrate”.',
    chirps_label: 'Chirps per speaker',
    run: 'Calibrate',
    run_note: 'It will be quiet at first, then the speakers take turns playing short'
      + ' chirps. Keep the phone still and the room quiet. Whatever was playing stops:'
      + ' the track is queued as ordinary playback — only that way do mute and grouping,'
      + ' which the measurement relies on, work.',
    result: 'Result',
    ms_spread: 'ms spread',
    check: 'Check without changes',
    check_note: '“Check” measures the speakers as they are now, at 44.1 and 48 kHz, with'
      + ' every speaker together at the end — and changes nothing. It shows whether the'
      + ' corrections hold, and whether a speaker\'s delay depends on the track format.',
    listen: 'Listen to clicks',
    listen_note: '“Listen” plays clicks on every speaker at once for about 20 s — no'
      + ' microphone. Stand where the phone was. One sharp click: in sync. A thick or'
      + ' ringing click: a few ms apart. A double “tr-ack”: more than ~10 ms, calibrate.',
    listening: 'Clicks are playing on every speaker. One sharp click means in sync;'
      + ' a double click means they are apart.',
    listening_done: 'Listening test over; the speakers are back as they were.',
    check_result: 'Check',
    offset_from_first: 'after the earliest',
    in_sync: 'In sync: the corrections hold, in both formats and with every speaker playing.',
    save_placeholder: 'Position name, e.g. “sofa”',
    save: 'Save',
    positions: 'Positions',
    positions_note: 'A calibration belongs to the spot the phone was in: it also'
      + ' compensates for sound travelling through the air. The sofa and the kitchen need'
      + ' different corrections — a saved position is applied without a new measurement.',
    disconnected: 'Connection lost, reconnecting…',
    recording: 'Recording…',
    computing: 'Computing…',
    error: 'Error: ',
    verifying: 'Verification pass…',
    measuring: 'Measuring…',
    playing: (v) => `Playing: ${v.name} (${v.round}/${v.rounds})`,
    everyone: 'every speaker at once',
    applying: (v) => `Applying corrections (${v.writes})…`,
    guard_too_many: (v) => `The first ${v.guard} chirps of each round are discarded — the`
      + ' switch-over masks them. More are needed.',
    readings: (v) => `${v.n} ${plural(v.n, ['reading', 'readings'])} per speaker.`,
    total: (v) => ` ${v.total} ${plural(v.total, ['chirp', 'chirps'])} in all:`
      + ' the first speaker plays twice, and the repeat measures the phone clock\'s drift.'
      + ` Measurement with verification ≈ ${v.seconds} s.`,
    settings_found: 'delay setting not found — show what the player has',
    settings_all: 'player settings',
    ms: 'ms',
    reference_pill: 'reference (not adjustable)',
    reference_hint: 'No delay setting: measured, and the others are aligned to it. Its settings are never written.',
    delay: 'Delay',
    verification: 'Verified',
    arrives: (v) => `arrives +${v.ms} ms`,
    unchanged: 'unchanged',
    plays_earlier: (v) => `plays ${v.ms} ms earlier`,
    plays_later: (v) => `plays ${v.ms} ms later`,
    moved_by: (v) => `moved ${v.observed} of ${v.expected} ms`,
    nothing_to_write: 'Already in line — nothing needed writing, so nothing was.',
    position_note: 'The alignment holds where the microphone stood; each metre closer to'
      + ' one speaker than the microphone was makes it ~3 ms early.',
    mic_level: 'Microphone',
    now_playing: 'Should be playing',
    mic_hears: 'Microphone hears',
    all_together: 'every speaker at once',
    nobody: '—',
    verdict_ok: 'test sound — good level',
    verdict_quiet: 'test sound — quiet, turn up',
    verdict_silent: 'no test sound',
    verdict_clipping: 'too loud — overdriven',
    tally_heard: (v) => `heard ${v.heard} of ${v.total}`,
    human_question: 'Only this speaker audible?',
    human_ok: '✓ yes',
    human_wrong: '✗ no, something else',
    human_thanks_ok: 'Noted: sounded right.',
    human_thanks_wrong: 'Noted — this run will not write anything.',
    mic_test: 'Test microphone',
    mic_test_stop: 'Stop microphone test',
    mic_test_note: 'Microphone open. Play something and watch the level; it should move but not turn red.',
    refining: 'Correcting the remaining difference …',
    measuring_attempt: (v) => `Measuring (${v.attempt} of ${v.planned}) …`,
    speaker_test: 'Speaker test (by ear)',
    speaker_test_note: '“Speaker test” plays each speaker on its own and then none, and asks'
      + ' you each time — take your time. It finds a speaker that keeps playing when muted,'
      + ' which would otherwise pass for the others in a measurement. Best run before calibrating.',
    speaker_test_running: 'Speaker test — listen, then answer.',
    ask_alone: (v) => `${v.index} of ${v.count}: do you hear only «${v.name}»?`,
    ask_alone_yes: 'Yes, only this one',
    ask_alone_no: 'No — another one too, or nothing',
    ask_silence: 'Every speaker is muted now. Is it silent?',
    ask_silence_yes: 'Yes, silent',
    ask_silence_no: 'No, I still hear it',
    speaker_test_passed: 'Every speaker played on its own and fell silent when muted —'
      + ' the measurement can trust its rounds.',
    silence_round: 'nobody (all muted)',
    ready_pill: 'ready',
    not_taking_part: 'not taking part',
    switch_off: 'switch off',
    switch_on: 'switch on',
    speaker: 'Speaker',
    no_players: 'Music Assistant reported no players',
    need_two: 'At least two speakers need to be switched on. The reasons are in the list above.',
    no_players_status: 'Music Assistant reported no players.',
    ready_mixed: (v) => `Ready, ${v.n} ${plural(v.n, ['speaker', 'speakers'])}. Some of them`
      + ' are not Sendspin — accuracy will depend on their own synchronisation.',
    ready: (v) => `Ready, ${v.n} ${plural(v.n, ['speaker', 'speakers'])}.`
      + ' Put the phone where you listen.',
    toggle_failed: 'Did not switch: ',
    limit: 'limit',
    centered: 'The spread cannot be covered by a one-sided delay, so the corrections are'
      + ' measured from the middle rather than from the slowest speaker.',
    fastest: 'The delay setting on these speakers can only advance, not delay, so'
      + ' everyone is pulled up to the fastest speaker.',
    does_not_fit: 'The spread does not fit within ±500 ms — some speakers cannot be'
      + ' fully aligned.',
    verified: 'The verification pass confirmed the result.',
    together_ok: (v) => `With every speaker playing at once: ${v.spread} ms apart, as measured one by one.`,
    done: 'Done.',
    done_with_notes: 'Finished with remarks.',
    nothing_saved: 'Nothing saved yet',
    n_speakers: (v) => `${v.n} ${plural(v.n, ['speaker', 'speakers'])}`,
    apply: 'Apply',
    delete: 'Delete',
    applying_position: (v) => `Applying “${v.name}”…`,
    applied_with_problems: (v) => `Applied (${v.n}), but: ${v.problems}`,
    applied: (v) => `Position “${v.name}” applied, speakers changed: ${v.n}.`
      + (v.n ? ' Nothing was measured — press “Check without changes” to confirm what you hear.' : ''),
    apply_failed: 'Could not apply: ',
    saved: (v) => `Position “${v.name}” saved.`,
    save_failed: 'Not saved: ',
    no_microphone: 'No access to the microphone: ',
  },
  ru: {
    tagline: 'Выравнивание задержек колонок по микрофону телефона',
    popout_text: 'Браузер может не дать микрофон странице внутри панели Home Assistant —',
    popout_link: 'откройте Speaker Sync Calibrator отдельно, без панели',
    needs_https: 'Браузер даёт микрофон только странице, открытой по https://, а Home'
      + ' Assistant сейчас открыт по http://. Откройте его по https-адресу (Home Assistant'
      + ' Cloud или собственный сертификат) — тогда калибровка заработает.',
    speakers: 'Колонки',
    refresh: 'Обновить',
    loading: 'Загрузка…',
    switch_note: 'Выключенную колонку калибровка не трогает: её не замеряют, в группу не'
      + ' берут и задержку ей не меняют. Пригодится для сабвуфера, колонки в другой'
      + ' комнате или той, что настроена вручную.',
    idle: 'Положите телефон туда, где слушаете, и нажмите «Калибровать».',
    chirps_label: 'Свистов на колонку',
    run: 'Калибровать',
    run_note: 'Во время замера будет тихо, потом колонки по очереди издадут короткие'
      + ' свисты. Не двигайте телефон и старайтесь не шуметь. То, что играло,'
      + ' остановится: трек ставится в очередь как обычное воспроизведение — только так'
      + ' работают мьют и группа, на которых держится замер.',
    result: 'Результат',
    ms_spread: 'мс разброса',
    check: 'Проверить без изменений',
    check_note: '«Проверить» меряет колонки как есть, на 44,1 и 48 кГц, в конце — все вместе,'
      + ' и ничего не меняет. Видно, держатся ли поправки и не зависит ли задержка'
      + ' колонки от формата трека.',
    listen: 'Послушать щелчки',
    listen_note: '«Послушать» играет щелчки на всех колонках сразу, около 20 с, без'
      + ' микрофона. Встаньте туда, где лежал телефон. Один чёткий щелчок — синхронно.'
      + ' «Толстый» или звенящий — расхождение в несколько мс. Двойной «тр-ак» — больше'
      + ' ~10 мс, нужна калибровка.',
    listening: 'Щелчки играют на всех колонках. Один чёткий щелчок — синхронно;'
      + ' двойной — колонки расходятся.',
    listening_done: 'Проверка на слух закончена; колонки вернулись в прежнее состояние.',
    check_result: 'Проверка',
    offset_from_first: 'после самой ранней',
    in_sync: 'Синхронно: поправки держатся — в обоих форматах и когда играют все сразу.',
    save_placeholder: 'Название позиции, например «диван»',
    save: 'Сохранить',
    positions: 'Позиции',
    positions_note: 'Калибровка привязана к точке, где стоял телефон: компенсируется в том'
      + ' числе путь звука по воздуху. Для дивана и кухни нужны разные поправки —'
      + ' сохранённую позицию можно применить без нового замера.',
    disconnected: 'Соединение потеряно, переподключаюсь…',
    recording: 'Идёт запись…',
    computing: 'Считаю…',
    error: 'Ошибка: ',
    verifying: 'Проверочный замер…',
    measuring: 'Замер…',
    playing: (v) => `Играет: ${v.name} (${v.round}/${v.rounds})`,
    everyone: 'все колонки сразу',
    applying: (v) => `Применяю поправки (${v.writes})…`,
    guard_too_many: (v) => `Первые ${v.guard} свиста в каждом круге отбрасываются — их`
      + ' заглушает переключение. Нужно больше.',
    readings: (v) => `${v.n} ${plural(v.n, ['отсчёт', 'отсчёта', 'отсчётов'])} на колонку.`,
    total: (v) => ` Всего ${v.total} ${plural(v.total, ['свист', 'свиста', 'свистов'])}:`
      + ' первая колонка звучит дважды, по повтору измеряется уход часов телефона.'
      + ` Замер с проверкой ≈ ${v.seconds} с.`,
    settings_found: 'настройка задержки не найдена — показать настройки плеера',
    settings_all: 'настройки плеера',
    ms: 'мс',
    reference_pill: 'опорная (не настраивается)',
    reference_hint: 'Нет настройки задержки: измеряется, остальные выравниваются по ней. Её настройки никогда не меняются.',
    delay: 'Задержка',
    verification: 'Проверка',
    arrives: (v) => `приходит +${v.ms} мс`,
    unchanged: 'без изменений',
    plays_earlier: (v) => `звучит на ${v.ms} мс раньше`,
    plays_later: (v) => `звучит на ${v.ms} мс позже`,
    moved_by: (v) => `сдвиг ${v.observed} из ${v.expected} мс`,
    nothing_to_write: 'Уже выровнено — записывать было нечего, и ничего не записано.',
    position_note: 'Выравнивание верно там, где стоял микрофон; каждый метр ближе к одной'
      + ' из колонок даёт ей ~3 мс опережения.',
    mic_level: 'Микрофон',
    now_playing: 'Сейчас должна звучать',
    mic_hears: 'Микрофон слышит',
    all_together: 'все колонки сразу',
    nobody: '—',
    verdict_ok: 'тестовый звук — уровень хороший',
    verdict_quiet: 'тестовый звук — тихо, сделайте громче',
    verdict_silent: 'тестового звука нет',
    verdict_clipping: 'слишком громко — перегруз',
    tally_heard: (v) => `слышно ${v.heard} из ${v.total}`,
    human_question: 'Слышна только эта колонка?',
    human_ok: '✓ да',
    human_wrong: '✗ нет, что-то другое',
    human_thanks_ok: 'Отмечено: звучало правильно.',
    human_thanks_wrong: 'Отмечено — этот запуск ничего не запишет.',
    mic_test: 'Проверить микрофон',
    mic_test_stop: 'Остановить проверку микрофона',
    mic_test_note: 'Микрофон открыт. Включите что-нибудь и следите за уровнем: он должен двигаться, но не краснеть.',
    refining: 'Доправляю оставшуюся разницу …',
    measuring_attempt: (v) => `Измеряю (${v.attempt} из ${v.planned}) …`,
    speaker_test: 'Проверка колонок (на слух)',
    speaker_test_note: '«Проверка колонок» включает каждую колонку по отдельности, затем ни одной,'
      + ' и каждый раз спрашивает вас — не торопитесь. Она находит колонку, которая играет при'
      + ' заглушении и иначе выдавала бы себя за другие при замере. Лучше перед калибровкой.',
    speaker_test_running: 'Проверка колонок — послушайте и ответьте.',
    ask_alone: (v) => `${v.index} из ${v.count}: слышна только «${v.name}»?`,
    ask_alone_yes: 'Да, только эта',
    ask_alone_no: 'Нет — ещё другая или ничего',
    ask_silence: 'Сейчас все колонки заглушены. Тишина?',
    ask_silence_yes: 'Да, тишина',
    ask_silence_no: 'Нет, всё ещё слышно',
    speaker_test_passed: 'Каждая колонка играла отдельно и замолкала при заглушении —'
      + ' замеру можно доверять.',
    silence_round: 'никто (все заглушены)',
    ready_pill: 'готова',
    not_taking_part: 'не участвует',
    switch_off: 'выключить',
    switch_on: 'включить',
    speaker: 'Колонка',
    no_players: 'Music Assistant не отдал ни одного плеера',
    need_two: 'Нужно минимум две включённые колонки. Причины — в списке выше.',
    no_players_status: 'Music Assistant не отдал ни одного плеера.',
    ready_mixed: (v) => `Готово, колонок: ${v.n}. Часть из них не Sendspin — точность`
      + ' будет зависеть от их собственной синхронизации.',
    ready: (v) => `Готово, колонок: ${v.n}. Положите телефон туда, где слушаете.`,
    toggle_failed: 'Не переключилось: ',
    limit: 'предел',
    centered: 'Разброс не покрывается односторонней задержкой, поэтому поправки отсчитаны'
      + ' от середины, а не от самой медленной колонки.',
    fastest: 'Настройка задержки на этих колонках умеет только торопить, но не задерживать,'
      + ' поэтому все подтянуты к самой быстрой колонке.',
    does_not_fit: 'Разброс не влезает в ±500 мс — часть колонок выровнять до конца нельзя.',
    verified: 'Проверочный замер подтвердил результат.',
    together_ok: (v) => `Когда играют все сразу: расхождение ${v.spread} мс, как и по одной.`,
    done: 'Готово.',
    done_with_notes: 'Завершено с замечаниями.',
    nothing_saved: 'Пока ничего не сохранено',
    n_speakers: (v) => `${v.n} ${plural(v.n, ['колонка', 'колонки', 'колонок'])}`,
    apply: 'Применить',
    delete: 'Удалить',
    applying_position: (v) => `Применяю «${v.name}»…`,
    applied_with_problems: (v) => `Применено (${v.n}), но: ${v.problems}`,
    applied: (v) => `Позиция «${v.name}» применена, изменено колонок: ${v.n}.`
      + (v.n ? ' Ничего не измерялось — нажмите «Проверить без изменений», чтобы подтвердить результат.' : ''),
    apply_failed: 'Не удалось применить: ',
    saved: (v) => `Позиция «${v.name}» сохранена.`,
    save_failed: 'Не сохранилось: ',
    no_microphone: 'Нет доступа к микрофону: ',
  },
};

function t(key, vars) {
  const text = STRINGS[LANG][key] ?? STRINGS.en[key] ?? key;
  return typeof text === 'function' ? text(vars || {}) : text;
}

// Static text in the page carries a key rather than words, so both languages
// live in one place.
function translatePage() {
  document.querySelectorAll('[data-i18n]').forEach((node) => {
    node.textContent = t(node.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach((node) => {
    node.placeholder = t(node.dataset.i18nPlaceholder);
  });
}

// Every URL is relative to the page, never to the host root: behind Home
// Assistant's ingress the app lives under /api/hassio_ingress/<token>/, and an
// absolute '/api/…' would land on Home Assistant's own API instead.
const here = (path) => new URL(path, location.href).href;

// Match the page's own scheme: wss behind the TLS-terminating proxy, ws when
// developing against http://localhost (which browsers count as a secure
// context, so the microphone still works there).
const socketUrl = here('ws').replace(/^http/, 'ws');

let socket = null;
let audio = null;      // AudioContext
let stream = null;     // MediaStream
let node = null;       // AudioWorkletNode
let recording = false;

function setStatus(text, kind) {
  el('status').textContent = text;
  el('dot').className = 'dot' + (kind ? ' ' + kind : '');
}

let busy = false;      // a measurement is running
let runnable = false;  // enough speakers are switched on to run one

// Kept apart deliberately. Switching a speaker off can leave too few to
// calibrate, and if that disabled the switches too, the user would have no way
// to switch it back on again.
function refreshControls() {
  el('run').disabled = busy || !runnable;
  el('speakertest').disabled = busy || !runnable;
  el('check').disabled = busy || !runnable;
  el('listen').disabled = busy || !runnable;
  el('refresh').disabled = busy;
  document.querySelectorAll('#players .toggle').forEach((b) => { b.disabled = busy; });
}

function setBusy(value) {
  busy = value;
  refreshControls();
}

function setProgress(fraction) {
  el('bar').style.width = Math.max(0, Math.min(1, fraction)) * 100 + '%';
}

// --------------------------------------------------------------- live view

// The level shown is the block's peak, held and let fall slowly, as on a
// mixing desk: chirps are short, and a meter that followed every block would
// flicker too fast to read.
const METER_FLOOR_DB = -60;
let heldPeakDb = METER_FLOOR_DB;
let meterQueued = false;
let latestBlock = null;

function showLevel(block) {
  latestBlock = block;
  if (meterQueued) return;
  meterQueued = true;
  requestAnimationFrame(() => {
    meterQueued = false;
    const samples = latestBlock;
    let peak = 0;
    let sum = 0;
    for (let i = 0; i < samples.length; i += 1) {
      const v = Math.abs(samples[i]);
      if (v > peak) peak = v;
      sum += v * v;
    }
    const peakDb = peak > 0 ? 20 * Math.log10(peak) : METER_FLOOR_DB;
    const rmsDb = sum > 0 ? 10 * Math.log10(sum / samples.length) : METER_FLOOR_DB;
    heldPeakDb = Math.max(peakDb, heldPeakDb - 1.5);
    const width = (db) => Math.max(0, Math.min(1, (db - METER_FLOOR_DB) / -METER_FLOOR_DB)) * 100;
    const fill = el('meter-fill');
    fill.style.width = width(rmsDb) + '%';
    fill.className = heldPeakDb > -1 ? 'clip' : heldPeakDb < -45 ? 'quiet' : '';
    el('meter-peak').style.left = width(heldPeakDb) + '%';
    el('meter-text').textContent = `${Math.round(heldPeakDb)} dBFS`;
  });
}

// Which speaker the server says should be sounding, and what the microphone
// made of each round so far: the two side by side are what tells whether the
// measurement is measuring what it claims to.
let livePlaying = null;
let tally = {};

function showLive(visible) {
  el('live').hidden = !visible;
}

function resetLive() {
  livePlaying = null;
  tally = {};
  el('live-playing').textContent = t('nobody');
  el('live-heard').textContent = '—';
  el('live-heard').className = 'pill';
  el('live-tally').innerHTML = '';
  el('human').hidden = true;
}

function liveName(playerId) {
  if (playerId === '*') return t('all_together');
  if (playerId === '-') return t('silence_round');
  return nameOf(playerId);
}

function onRound(message) {
  livePlaying = message.player_id;
  el('live-playing').textContent = liveName(livePlaying);
  // Asked again every round: the answer is about this speaker only.
  el('human').hidden = false;
  el('human-ok').disabled = false;
  el('human-wrong').disabled = false;
}

function onLive(reading) {
  const pill = el('live-heard');
  pill.textContent = t('verdict_' + reading.verdict);
  pill.className = 'pill ' + ({ ok: 'on', quiet: 'warn', silent: 'off', clipping: 'off' })[reading.verdict];
  if (!livePlaying) return;
  const entry = tally[livePlaying] || (tally[livePlaying] = { heard: 0, total: 0, worst: 'ok' });
  entry.total += 1;
  if (reading.heard) entry.heard += 1;
  const rank = { ok: 0, quiet: 1, silent: 2, clipping: 3 };
  if (reading.heard && rank[reading.verdict] > rank[entry.worst]) entry.worst = reading.verdict;
  renderTally();
}

function renderTally() {
  el('live-tally').innerHTML = '<tbody>' + Object.entries(tally).map(([pid, e]) => {
    // The first window or two of a round still carry the previous speaker or
    // the settling gap, so "most of them" is the bar, not "all".
    const good = e.total && e.heard / e.total >= 0.5;
    const kind = !good ? 'off' : e.worst === 'ok' ? 'on' : 'warn';
    return `<tr><td style="text-align:left">${escapeHtml(liveName(pid))}</td>`
      + `<td><span class="pill ${kind}">${t('tally_heard', e)}</span></td></tr>`;
  }).join('') + '</tbody>';
}

function sendFeedback(ok) {
  if (!livePlaying || !socket || socket.readyState !== WebSocket.OPEN) return;
  socket.send(JSON.stringify({ type: 'human_feedback', player_id: livePlaying, ok }));
  el('human-ok').disabled = true;
  el('human-wrong').disabled = true;
  setStatus(t(ok ? 'human_thanks_ok' : 'human_thanks_wrong'), ok ? 'live' : 'err');
}

// ------------------------------------------------------------ speaker test

let askedQuestion = null;

function socketOpen() {
  return socket && socket.readyState === WebSocket.OPEN;
}

function askListener(question) {
  askedQuestion = question.question_id;
  const alone = question.step === 'alone';
  el('ask-question').textContent = alone ? t('ask_alone', question) : t('ask_silence');
  el('ask-yes').textContent = t(alone ? 'ask_alone_yes' : 'ask_silence_yes');
  el('ask-no').textContent = t(alone ? 'ask_alone_no' : 'ask_silence_no');
  el('ask-yes').disabled = false;
  el('ask-no').disabled = false;
  el('ask').hidden = false;
  el('ask').scrollIntoView({ block: 'nearest' });
}

function answerListener(ok) {
  if (!socketOpen()) return;
  el('ask-yes').disabled = true;
  el('ask-no').disabled = true;
  socket.send(JSON.stringify({ type: 'speaker_test_answer', question_id: askedQuestion, ok }));
}

function speakerTestDone(message) {
  el('ask').hidden = true;
  setStatus(
    message.passed ? t('speaker_test_passed') : message.problems.join('\n\n'),
    message.passed ? 'ok' : 'err',
  );
  setBusy(false);
}

function speakerTest() {
  if (!socketOpen()) {
    setStatus(t('disconnected'), 'err');
    return;
  }
  setBusy(true);
  setProgress(0);
  showLive(false);
  setStatus(t('speaker_test_running'), 'live');
  socket.send(JSON.stringify({ type: 'speaker_test' }));
}

let micTesting = false;

async function toggleMicTest() {
  if (micTesting) {
    micTesting = false;
    el('mictest').textContent = t('mic_test');
    if (!busy) showLive(false);
    return;
  }
  try {
    await openMicrophone();
    if (audio.state === 'suspended') await audio.resume();
    micTesting = true;
    el('mictest').textContent = t('mic_test_stop');
    resetLive();
    showLive(true);
    setStatus(t('mic_test_note'), 'live');
  } catch (error) {
    setStatus(t('no_microphone') + error.message, 'err');
  }
}

// --------------------------------------------------------------- microphone

async function openMicrophone() {
  if (audio && audio.state !== 'closed') return;

  // Every piece of browser "helpfulness" here is actively harmful. Echo
  // cancellation would suppress precisely the signal being measured, noise
  // suppression would gate the chirp, and automatic gain would move the
  // levels mid-measurement.
  stream = await navigator.mediaDevices.getUserMedia({
    audio: {
      echoCancellation: false,
      noiseSuppression: false,
      autoGainControl: false,
      channelCount: 1,
    },
  });

  audio = new AudioContext();
  await audio.audioWorklet.addModule('static/recorder-worklet.js');

  node = new AudioWorkletNode(audio, 'speaker-sync-recorder');
  node.port.onmessage = (event) => {
    showLevel(event.data);
    if (recording && socket && socket.readyState === WebSocket.OPEN) {
      socket.send(event.data.buffer);
    }
  };

  audio.createMediaStreamSource(stream).connect(node);
  // Keep the graph pulling without routing the microphone to the speakers.
  const sink = audio.createGain();
  sink.gain.value = 0;
  node.connect(sink).connect(audio.destination);
}

// ------------------------------------------------------------------- socket

function connect() {
  socket = new WebSocket(socketUrl);
  socket.binaryType = 'arraybuffer';

  // The player list owns the status line: it is the thing that knows whether
  // a calibration can actually start. Announcing "ready" here would overwrite
  // an explanation of why the buttons are disabled.
  socket.onopen = () => {
    // A job does not survive its socket — the server cancels it and puts the
    // speakers back — so a new connection starts with nothing running.
    // Left busy, every button stayed disabled until the page was reloaded.
    recording = false;
    el('ask').hidden = true;
    setBusy(false);
    refreshPlayers();
  };
  socket.onclose = () => {
    // Stop streaming the microphone: there is no recording to feed any more.
    recording = false;
    setStatus(t('disconnected'), 'err');
    setBusy(true);
    setTimeout(connect, 2000);
  };
  socket.onmessage = (event) => handle(JSON.parse(event.data));
}

function handle(message) {
  switch (message.type) {
    case 'record_start':
      recording = true;
      setStatus(t('recording'), 'live');
      // The rate goes ahead of the audio so the server can judge each
      // window as it arrives rather than only at the end.
      socket.send(JSON.stringify({
        type: 'recording_format',
        sample_rate: audio ? audio.sampleRate : 48000,
      }));
      showLive(true);
      break;

    case 'live':
      onLive(message);
      break;

    case 'speaker_test_ask':
      askListener(message);
      break;

    case 'speaker_test_done':
      speakerTestDone(message);
      break;

    case 'record_stop':
      recording = false;
      el('human').hidden = true;
      socket.send(JSON.stringify({
        type: 'recording_done',
        sample_rate: audio ? audio.sampleRate : 48000,
      }));
      setStatus(t('computing'), 'live');
      break;

    case 'progress':
      onProgress(message);
      break;

    case 'sign':
      setStatus(message.detail, message.conclusive ? 'ok' : 'err');
      setBusy(false);
      refreshPlayers();
      break;

    case 'check':
      showCheck(message);
      setBusy(false);
      refreshPlayers();
      break;

    case 'listening':
      // Still busy: the group is held until the track ends.
      setStatus(t('listening'), 'live');
      break;

    case 'listening_done':
      setStatus(
        message.problems && message.problems.length
          ? t('error') + message.problems.join(' ')
          : t('listening_done'),
        message.problems && message.problems.length ? 'err' : 'ok',
      );
      setBusy(false);
      break;

    case 'report':
      showReport(message);
      setBusy(false);
      refreshPlayers();
      // A result now exists, so saving it as a position becomes possible.
      refreshProfiles();
      break;

    case 'error':
      setStatus(t('error') + message.message, 'err');
      el('ask').hidden = true;
      setBusy(false);
      break;
  }
}

let passOffset = 0;
let passSpan = 1;

function onProgress(message) {
  if (message.stage === 'pass') {
    // A calibration measures `planned` times, then verifies; a check is one
    // pass per track format. Extra passes (a speaker unheard, passes that
    // disagree) and refinements reuse the last stretch of the bar.
    const planned = (message.planned || 1) + 1;
    if (message.which === 'before') {
      const index = Math.min(message.attempt || 1, planned - 1) - 1;
      passOffset = index / planned;
      passSpan = 1 / planned;
      setStatus(message.planned > 1
        ? t('measuring_attempt', { attempt: message.attempt, planned: message.planned })
        : t('measuring'), 'live');
    } else if (message.which === 'check') {
      passOffset = message.rate === 48000 ? 0.5 : 0;
      passSpan = 0.5;
      setStatus(t('measuring'), 'live');
    } else {
      passOffset = 1 - 1 / Math.max(planned, 2);
      passSpan = 1 / Math.max(planned, 2);
      setStatus(t(message.which === 'refine' ? 'refining' : 'verifying'), 'live');
    }
  } else if (message.stage === 'round') {
    onRound(message);
    setProgress(passOffset + passSpan * (message.round / message.rounds));
    setStatus(t('playing', {
      name: nameOf(message.player_id), round: message.round, rounds: message.rounds,
    }), 'live');
  } else if (message.stage === 'applying') {
    setStatus(t('applying', { writes: message.writes }), 'live');
  }
}

// ----------------------------------------------------------- round length

// Filled from the server so the page never invents session parameters, and so
// a value chosen on one device shows up on the next.
let session = { chirps_per_round: 5, guard_chirps: 2, period_seconds: 1.3 };

function chosenChirps() {
  const asked = parseInt(el('chirps').value, 10);
  return Number.isFinite(asked) ? asked : session.chirps_per_round;
}

function describeRoundLength() {
  const chirps = chosenChirps();
  const readings = chirps - session.guard_chirps;
  const ready = players.filter((p) => p.measured).length;

  if (readings < 1) {
    el('chirps-note').textContent = t('guard_too_many', { guard: session.guard_chirps });
    return;
  }

  // One round per speaker, plus a repeat of the first to measure clock drift,
  // and the whole thing runs twice: measure, then verify — the verification
  // with one more round at the end, every speaker at once.
  const rounds = ready ? ready + 1 : 0;
  const total = rounds * chirps;
  const passes = (session.measure_passes || 1) + 1;
  const seconds = Math.round((passes * total + (rounds ? chirps : 0)) * session.period_seconds);

  let note = t('readings', { n: readings });
  if (rounds) {
    // Spelled out because the first speaker sounding twice is otherwise a
    // surprise: at five per round it emits ten, and the count looks stuck.
    note += t('total', { total, seconds });
  }
  el('chirps-note').textContent = note;
}

// ------------------------------------------------------------------ players

let players = [];

function nameOf(playerId) {
  if (playerId === '*') return t('everyone');
  const found = players.find((p) => p.player_id === playerId);
  return found ? found.name : playerId;
}

// While Music Assistant is out of reach the server says why with a 503; the
// list is asked for again until it answers.
const RECONNECT_POLL_MS = 5000;
let reconnectTimer = null;

async function refreshPlayers() {
  clearTimeout(reconnectTimer);
  const response = await fetch('api/players');
  if (!response.ok) {
    players = [];
    runnable = false;
    refreshControls();
    el('players').innerHTML = '';
    setStatus((await response.text()).trim() || response.statusText, 'err');
    if (response.status === 503) {
      reconnectTimer = setTimeout(refreshPlayers, RECONNECT_POLL_MS);
    }
    return;
  }
  const data = await response.json();
  players = data.players;
  session = data;

  const chirps = el('chirps');
  chirps.min = data.chirps_range[0];
  chirps.max = data.chirps_range[1];
  // Only while the field is not being edited, or typing would fight the poll.
  if (document.activeElement !== chirps) chirps.value = data.chirps_per_round;

  // Re-rendering would fold every open settings list back up.
  const unfolded = new Set(
    [...document.querySelectorAll('#players details[open]')].map((d) => d.dataset.player),
  );

  const rows = players.map((p) => `
    <tr class="${p.enabled && p.renders_audio !== false ? '' : 'off'}">
      <td>${escapeHtml(p.name)}<br><span class="sub">${escapeHtml(p.transport)}</span>${
        // Always folded away: the names are for diagnosis, not for reading.
        // The summary says so when they matter — the delay setting was not
        // found, and seeing what is there turns that into a one-line fix.
        // A group has no delay setting by nature, so nothing to diagnose.
        p.renders_audio !== false && p.config_keys && p.config_keys.length
          ? `<details class="keys" data-player="${escapeAttr(p.player_id)}"${
              unfolded.has(p.player_id) ? ' open' : ''}><summary>${t(
              p.enabled && p.available && !p.sync_adjust_key && !p.reference
                ? 'settings_found' : 'settings_all'
            )}</summary>${escapeHtml(p.config_keys.join(', '))}</details>`
          : ''
      }${
        // A failed read is a different fault from an absent setting, and the
        // server's own words are what identify it.
        p.config_error
          ? `<br><span class="sub bad">${escapeHtml(p.config_error)}</span>`
          : ''
      }</td>
      <td class="num">${p.sync_adjust_key
        ? `${p.sync_adjust_ms > 0 ? '+' : ''}${p.sync_adjust_ms} ${t('ms')}`
        : '—'}</td>
      <td class="verdict">
        <span class="pill ${p.measured ? 'on' : 'off'}"${
          p.reference ? ` title="${escapeAttr(t('reference_hint'))}"` : ''}>${
          escapeHtml(p.reference
            ? t('reference_pill')
            : p.calibratable ? t('ready_pill') : (p.excluded_because || t('not_taking_part')))
        }</span>${
        // A group is never measured either way, so a switch would do nothing.
        p.renders_audio === false ? '' : `
        <button class="toggle" data-toggle="${escapeAttr(p.player_id)}"
                data-enable="${p.enabled ? '0' : '1'}"${busy ? ' disabled' : ''}>${
          t(p.enabled ? 'switch_off' : 'switch_on')
        }</button>`}
      </td>
    </tr>`).join('');

  el('players').innerHTML =
    `<thead><tr><th>${t('speaker')}</th><th>sync_adjust</th><th></th></tr></thead>
     <tbody>${rows || `<tr><td colspan="3">${t('no_players')}</td></tr>`}</tbody>`;

  // References count towards the two a session needs; at least one speaker
  // still has to be adjustable for a calibration to have anything to write.
  const ready = players.filter((p) => p.measured);
  runnable = ready.length >= 2 && ready.some((p) => p.calibratable);
  refreshControls();
  describeRoundLength();

  if (!runnable) {
    setStatus(
      t(players.length ? 'need_two' : 'no_players_status'),
      'err',
    );
  } else if (ready.some((p) => !p.is_sendspin)) {
    // Sendspin guarantees the tightest playback sync; other providers still
    // work, since any offset they add is measured and corrected, but the
    // result is only as steady as their own synchronisation.
    setStatus(t('ready_mixed', { n: ready.length }));
  } else {
    setStatus(t('ready', { n: ready.length }));
  }
}

async function setPlayerEnabled(playerId, enabled) {
  try {
    const response = await fetch(`api/players/${encodeURIComponent(playerId)}/enabled`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }),
    });
    if (!response.ok) throw new Error((await response.text()).trim());
  } catch (error) {
    setStatus(t('toggle_failed') + error.message, 'err');
    return;
  }
  // The list owns the status line, so it has the last word on what the
  // switch changed — including whether a run is still possible.
  await refreshPlayers();
}

// ------------------------------------------------------------------- report

function showReport(report) {
  el('result').classList.remove('hidden');
  setProgress(1);

  // Small spreads are the interesting ones, so they keep their decimal.
  const ms = (value) => (value < 10 ? value.toFixed(1) : value.toFixed(0));
  // Nothing written because nothing needed writing is a result, not a fault.
  const settled = report.written === 0 && !report.problems.length;
  el('before').textContent = ms(report.spread_before_ms);
  const after = el('after');
  after.textContent = report.spread_after_ms === null
    ? (settled ? ms(report.spread_before_ms) : '—')
    : ms(report.spread_after_ms);
  after.className = 'headline ' + (report.improved || settled ? 'good' : 'bad');

  const moved = (p) => {
    if (p.reference) return `<span class="sub">${t('reference_pill')}</span>`;
    if (!p.moves_ms) return `<span class="sub">${t('unchanged')}</span>`;
    return `<span class="sub">${t(p.moves_ms < 0 ? 'plays_earlier' : 'plays_later',
                                  { ms: Math.abs(p.moves_ms) })}</span>`;
  };
  const checked = (p) => {
    const v = p.verification;
    if (!v) return '—';
    const text = t('moved_by', {
      observed: v.observed_ms.toFixed(1), expected: v.expected_ms.toFixed(1),
    });
    return `<span class="pill ${v.held ? 'on' : 'off'}">${v.held ? '✓' : '✗'}</span>`
      + `<br><span class="sub">${escapeHtml(text)}</span>`;
  };

  el('corrections').innerHTML =
    `<thead><tr><th>${t('speaker')}</th><th>${t('delay')}</th>`
    + `<th>${t('verification')}</th></tr></thead><tbody>` +
    report.players.map((p) => `
      <tr>
        <td>${escapeHtml(p.name)}${p.clamped ? ` <span class="pill off">${t('limit')}</span>` : ''}
          <br><span class="sub">${t('arrives', { ms: p.arrival_ms.toFixed(1) })}</span></td>
        <td class="num">${p.reference ? '—' : `${p.current_adjust_ms} → <b>${p.target_adjust_ms}</b> ${t('ms')}`}
          <br>${moved(p)}</td>
        <td class="num">${checked(p)}</td>
      </tr>`).join('') + '</tbody>';

  const notes = [];
  if (report.strategy === 'centered') {
    notes.push(['warn', t('centered')]);
  }
  if (report.strategy === 'align_to_fastest') {
    notes.push(['', t('fastest')]);
  }
  // A reference that arrives too late explains itself among the problems.
  if (!report.fits && report.strategy !== 'reference_too_late') {
    notes.push(['bad', t('does_not_fit')]);
  }
  report.problems.forEach((p) => notes.push(['bad', p]));
  if (!notes.length && report.improved) {
    notes.push(['', t('verified')]);
  }
  if (settled) {
    notes.push(['', t('nothing_to_write')]);
  }
  // The calibration holds for where the microphone stood.
  notes.push(['', t('position_note')]);
  if (report.together && report.together.confirmed) {
    notes.push(['', t('together_ok', { spread: report.together.spread_ms.toFixed(1) })]);
  }

  el('notes').innerHTML = notes
    .map(([kind, text]) => `<p class="note ${kind}">${escapeHtml(text)}</p>`)
    .join('');

  const good = report.improved || settled;
  setStatus(t(good ? 'done' : 'done_with_notes'), good ? 'ok' : 'err');
}

function showCheck(check) {
  el('check-result').classList.remove('hidden');
  setProgress(1);

  const spread = el('check-spread');
  spread.textContent = check.spread_ms.toFixed(check.spread_ms < 10 ? 1 : 0);
  spread.className = 'headline ' + (check.in_sync ? 'good' : 'bad');

  const khz = (rate) => `${(rate / 1000).toLocaleString(LANG)} ${LANG === 'ru' ? 'кГц' : 'kHz'}`;
  el('check-table').innerHTML =
    `<thead><tr><th>${t('speaker')}</th>`
    + check.rates.map((r) => `<th>${khz(r)}</th>`).join('')
    + `</tr></thead><tbody>` +
    check.players.map((p) => `
      <tr>
        <td>${escapeHtml(p.name)}</td>
        ${p.offsets_ms.map((v) => `<td class="num">${
          v === null ? '—' : `+${v.toFixed(1)} ${t('ms')}`}</td>`).join('')}
      </tr>`).join('') + '</tbody>'
    + `<caption class="sub">${t('offset_from_first')}</caption>`;

  const notes = check.problems.map((p) => ['bad', p]);
  if (check.in_sync) notes.push(['', t('in_sync')]);
  if (check.together && check.together.confirmed) {
    notes.push(['', t('together_ok', { spread: check.together.spread_ms.toFixed(1) })]);
  }
  el('check-notes').innerHTML = notes
    .map(([kind, text]) => `<p class="note ${kind}">${escapeHtml(text)}</p>`)
    .join('');

  setStatus(t(check.in_sync ? 'done' : 'done_with_notes'), check.in_sync ? 'ok' : 'err');
}

async function listen() {
  if (!socketOpen()) {
    setStatus(t('disconnected'), 'err');
    return;
  }
  setBusy(true);
  setStatus(t('listening'), 'live');
  socket.send(JSON.stringify({ type: 'listen' }));
}

// ----------------------------------------------------------------- profiles

async function refreshProfiles() {
  const response = await fetch('api/profiles');
  if (!response.ok) {
    // No state directory configured: the feature is simply off.
    el('profiles-card').classList.add('hidden');
    return;
  }

  const data = await response.json();
  el('profiles-card').classList.remove('hidden');
  el('save').disabled = !data.can_save;

  if (!data.profiles.length) {
    el('profiles').innerHTML =
      `<tbody><tr><td>${t('nothing_saved')}</td></tr></tbody>`;
    return;
  }

  el('profiles').innerHTML = '<tbody>' + data.profiles.map((p) => `
    <tr>
      <td>${escapeHtml(p.name)}<br><span class="pill">${t('n_speakers', { n: p.speakers })}</span></td>
      <td class="actions">
        <button data-apply="${escapeAttr(p.name)}">${t('apply')}</button>
        <button class="link" data-delete="${escapeAttr(p.name)}">${t('delete')}</button>
      </td>
    </tr>`).join('') + '</tbody>';
}

async function applyProfile(name) {
  setBusy(true);
  setStatus(t('applying_position', { name }), 'live');
  try {
    const response = await fetch(`api/profiles/${encodeURIComponent(name)}/apply`, {
      method: 'POST',
    });
    if (!response.ok) throw new Error(await response.text());

    const result = await response.json();
    const written = result.applied.length;
    setStatus(
      result.problems.length
        ? t('applied_with_problems', { n: written, problems: result.problems.join('; ') })
        : t('applied', { name, n: written }),
      result.problems.length ? 'err' : 'ok',
    );
  } catch (error) {
    setStatus(t('apply_failed') + error.message, 'err');
  } finally {
    setBusy(false);
    refreshPlayers();
  }
}

async function saveProfile() {
  const name = el('save-name').value.trim();
  if (!name) return;

  const response = await fetch('api/profiles', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ name }),
  });
  if (response.ok) {
    el('save-name').value = '';
    setStatus(t('saved', { name }), 'ok');
    refreshProfiles();
  } else {
    setStatus(t('save_failed') + (await response.text()), 'err');
  }
}

async function deleteProfile(name) {
  await fetch(`api/profiles/${encodeURIComponent(name)}`, { method: 'DELETE' });
  refreshProfiles();
}

function escapeAttr(value) {
  return String(value).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
}

function escapeHtml(value) {
  const node = document.createElement('span');
  node.textContent = String(value);
  return node.innerHTML;
}

// --------------------------------------------------------------------- boot

async function start(kind) {
  if (!socketOpen()) {
    setStatus(t('disconnected'), 'err');
    return;
  }
  try {
    setBusy(true);
    setProgress(0);
    resetLive();
    await openMicrophone();
    if (audio.state === 'suspended') await audio.resume();
    socket.send(JSON.stringify({ type: kind, chirps_per_round: chosenChirps() }));
  } catch (error) {
    if (!window.isSecureContext) {
      // Over plain http there is no microphone API at all, framed or not, and
      // the browser's own error ("undefined is not an object") explains nothing.
      setStatus(t('needs_https'), 'err');
    } else {
      setStatus(t('no_microphone') + error.message, 'err');
      // Inside Home Assistant's panel the page is an iframe, and whether it may
      // ask for the microphone is the embedding page's call, not ours. The same
      // ingress address works on its own, where the browser asks directly.
      if (window.top !== window.self) el('popout').hidden = false;
    }
    setBusy(false);
  }
}

el('chirps').addEventListener('input', describeRoundLength);
el('run').addEventListener('click', () => start('calibrate'));
el('check').addEventListener('click', () => start('check'));
el('listen').addEventListener('click', listen);
el('mictest').addEventListener('click', toggleMicTest);
el('speakertest').addEventListener('click', speakerTest);
el('ask-yes').addEventListener('click', () => answerListener(true));
el('ask-no').addEventListener('click', () => answerListener(false));
el('human-ok').addEventListener('click', () => sendFeedback(true));
el('human-wrong').addEventListener('click', () => sendFeedback(false));
el('save').addEventListener('click', saveProfile);
el('refresh').addEventListener('click', refreshPlayers);

// Delegated so the list can be re-rendered without rebinding every row.
el('players').addEventListener('click', (event) => {
  const toggle = event.target.closest('[data-toggle]');
  if (toggle) setPlayerEnabled(toggle.dataset.toggle, toggle.dataset.enable === '1');
});

el('profiles').addEventListener('click', (event) => {
  const apply = event.target.closest('[data-apply]');
  if (apply) return applyProfile(apply.dataset.apply);

  const remove = event.target.closest('[data-delete]');
  if (remove) return deleteProfile(remove.dataset.delete);
});

translatePage();
// Said up front: over http no button that needs the microphone can ever work.
if (!window.isSecureContext) el('insecure').hidden = false;
refreshPlayers();
refreshProfiles();
connect();
