import test from 'node:test';
import assert from 'node:assert/strict';
import { checkAnswer, mountPuzzle, INITIAL_MESSAGE } from '../site/app.mjs';

test('recognizes an answer regardless of case, article, and surrounding whitespace', () => {
  for (const answer of ['keyboard', '  KEYBOARD  ', 'a keyboard', 'a   computer keyboard']) {
    assert.match(checkAnswer(answer), /That’s it/);
  }
});

test('empty and incorrect answers give useful feedback', () => {
  assert.equal(checkAnswer(' \n '), 'Type an answer first.');
  assert.match(checkAnswer('piano'), /Not quite/);
  assert.match(checkAnswer('<script>alert(1)</script>'), /Not quite/);
});

test('form submission prevents navigation and reset restores feedback and focus', () => {
  const listeners = {};
  const form = { addEventListener: (name, handler) => { listeners[name] = handler; } };
  let focused = false;
  const answer = { value: 'Keyboard', focus: () => { focused = true; } };
  const feedback = { textContent: '' };
  const nodes = { '#answer-form': form, '#answer': answer, '#feedback': feedback };
  mountPuzzle({ querySelector: (selector) => nodes[selector] });
  let prevented = false;
  listeners.submit({ preventDefault: () => { prevented = true; } });
  assert.equal(prevented, true);
  assert.match(feedback.textContent, /That’s it/);
  listeners.reset();
  assert.equal(feedback.textContent, INITIAL_MESSAGE);
  assert.equal(focused, true);
});

test('module can be reused on pages without the puzzle form', () => {
  assert.doesNotThrow(() => mountPuzzle({ querySelector: () => null }));
});
