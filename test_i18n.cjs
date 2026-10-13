'use strict';
const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function browser(saved, blocked = false) {
  const listeners = {}, events = [], writes = [];
  const selector = {value: '', addEventListener: (type, fn) => { listeners[type] = fn; }};
  const heading = {dataset: {i18n: 'Каталог товаров'}, textContent: ''};
  const input = {getAttribute: () => 'Поиск по названию товара', setAttribute: (name, value) => { input[name] = value; }};
  const document = {
    documentElement: {lang: ''},
    getElementById: () => selector,
    querySelectorAll: query => query === '[data-i18n]' ? [heading] : query === '[data-i18n-aria-label]' ? [input] : [],
  };
  const context = vm.createContext({
    document,
    localStorage: {
      getItem: () => { if (blocked) throw Error('disabled'); return saved; },
      setItem: (key, value) => { if (blocked) throw Error('disabled'); writes.push([key, value]); },
    },
    window: {dispatchEvent: event => events.push(event.type)},
    Event: class { constructor(type) { this.type = type; } },
  });
  vm.runInContext(fs.readFileSync(path.join(__dirname, 'static/i18n.js'), 'utf8'), context);
  return {
    document, heading, input, selector, events, writes,
    evaluate: code => vm.runInContext(code, context),
    change: value => listeners.change({target: {value}}),
  };
}

test('switches both ways, updates accessible labels, persists only valid choices', () => {
  const app = browser(null);
  assert.equal(app.heading.textContent, 'Каталог товаров');
  app.change('en');
  assert.equal(app.document.documentElement.lang, 'en');
  assert.equal(app.heading.textContent, 'Product catalogue');
  assert.equal(app.input['aria-label'], 'Search by product name');
  assert.equal(app.selector.value, 'en');
  assert.deepEqual(app.writes, [['wien-katalog.language', 'en']]);
  assert.deepEqual(app.events, ['languagechange']);
  app.change('en');
  app.change('unsupported');
  assert.equal(app.events.length, 1);
  app.change('ru');
  assert.equal(app.heading.textContent, 'Каталог товаров');
  assert.equal(app.input['aria-label'], 'Поиск по названию товара');
});

test('restores saved language and works with unavailable storage', () => {
  assert.equal(browser('en').document.documentElement.lang, 'en');
  assert.equal(browser('invalid').document.documentElement.lang, 'ru');
  const app = browser(null, true);
  app.change('en');
  assert.equal(app.heading.textContent, 'Product catalogue');
});

test('translates interpolated UI and server messages without changing retailer wording', () => {
  const app = browser('en');
  assert.equal(app.evaluate("t('{0}–{1} из {2}', 1, 60, 100)"), '1–60 of 100');
  assert.equal(app.evaluate("t('Страница 3 из 8')"), 'Page 3 of 8');
  assert.equal(app.evaluate("t('0,5 кг')"), '0.5 kg');
  assert.equal(app.evaluate("t('От 2 шт., цена за одну')"), 'From 2 items, price per item');
  assert.match(app.evaluate("t('Сайт магазина ответил HTTP 403. Сохранённые цены остаются доступны.')"), /HTTP 403/);
  assert.equal(app.evaluate("t('NÖM PRO 35 g Protein')"), 'NÖM PRO 35 g Protein');
  assert.equal(app.evaluate("t('ab 2 Packungen')"), 'ab 2 Packungen');
  assert.equal(app.evaluate("t('Нет результатов')"), 'No results');
});

test('every static and scripted UI phrase has an English translation', () => {
  const app = browser('en'), phrases = new Set();
  for (const filename of ['app.js', 'offers.js', 'shopping.js', 'matching.js', 'history.js']) {
    const source = fs.readFileSync(path.join(__dirname, 'static', filename), 'utf8');
    for (const match of source.matchAll(/\bt\(("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')/g)) {
      const phrase = vm.runInNewContext(match[1]);
      if (/[А-Яа-яЁё]/.test(phrase)) phrases.add(phrase);
    }
  }
  const html = fs.readFileSync(path.join(__dirname, 'static/index.html'), 'utf8');
  for (const match of html.matchAll(/data-i18n(?:-[a-z-]+)?="([^"]+)"/g)) phrases.add(match[1]);
  const missing = [...phrases].filter(key => !app.evaluate(`Object.hasOwn(english, ${JSON.stringify(key)})`));
  assert.deepEqual(missing, []);
});

test('network error explanations have English translations', () => {
  const app = browser('en');
  const source = fs.readFileSync(path.join(__dirname, 'sources.py'), 'utf8');
  const messages = source.match(/NETWORK_MESSAGES = \{([\s\S]*?)\n\}/)[1];
  for (const [, phrase] of messages.matchAll(/'\w+': '([^']+)'/g)) {
    const translated = app.evaluate(`t(${JSON.stringify(phrase)})`);
    assert.doesNotMatch(translated, /[А-Яа-яЁё]/, phrase);
  }
});
