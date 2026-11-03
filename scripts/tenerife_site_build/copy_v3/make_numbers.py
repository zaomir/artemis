"""Export the current model's explicit financial tokens for editorial review."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from make_model import build_model

model = build_model()
lines = ['# Числа модели денежного выхода', '',
         'Источник: `model_inputs.json`. База рынка и рост — допущения; доходность — цель сценария.', '',
         '| Токен | Значение |', '|---|---|']
lines += [f"| {t['copy']} | {t['value']} |" for t in model['tokens']]
(Path(__file__).resolve().parent / 'numbers.md').write_text('\n'.join(lines)+'\n', encoding='utf-8')
print('numbers.md: explicit tokens exported from the current exit model')
