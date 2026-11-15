export const INITIAL_MESSAGE = 'Take your time. There’s no timer here.';

export function checkAnswer(answer) {
  const normalized = answer.trim().toLowerCase().replace(/\s+/g, ' ');
  if (!normalized) return 'Type an answer first.';
  return ['keyboard', 'a keyboard', 'computer keyboard', 'a computer keyboard'].includes(normalized)
    ? 'That’s it — a keyboard! A little curiosity goes a long way.'
    : 'Not quite. Hint: you might be using one right now. Try again.';
}

export function mountPuzzle(document) {
  const form = document.querySelector('#answer-form');
  const answer = document.querySelector('#answer');
  const feedback = document.querySelector('#feedback');
  if (!form || !answer || !feedback) return;
  form.addEventListener('submit', (event) => {
    event.preventDefault();
    feedback.textContent = checkAnswer(answer.value);
  });
  form.addEventListener('reset', () => {
    feedback.textContent = INITIAL_MESSAGE;
    answer.focus();
  });
}

if (typeof document !== 'undefined') mountPuzzle(document);
