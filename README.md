# Sistema de Notas - Motor de Diagnóstico SAEP

Script CLI para processar dados de simulados SAEP (CSV/JSON) e gerar diagnóstico por competência com saída JSON estruturada.

## Uso

```bash
python3 saep_diagnostico.py < entrada.csv
```

Também aceita JSON como entrada via stdin.

## Saída

- `{"aluno": {...}}` para um único aluno.
- `{"alunos": [...]}` para múltiplos alunos.

O script calcula automaticamente:
- `acertou` quando ausente;
- `peso` por `bloom/dificuldade` quando ausente;
- métricas gerais e por competência;
- plano de estudos de 7 dias e ações instrucionais.
