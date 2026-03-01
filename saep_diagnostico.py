#!/usr/bin/env python3
import csv
import io
import json
import re
import sys
from collections import defaultdict, Counter
from datetime import datetime

BLOOM_PESOS = {
    "fácil": 1.0,
    "facil": 1.0,
    "médio": 1.5,
    "medio": 1.5,
    "difícil": 2.0,
    "dificil": 2.0,
    "superdifícil": 3.0,
    "superdificil": 3.0,
}


def _norm(s):
    return str(s).strip() if s is not None else ""


def _to_float(value, default=None):
    if value is None:
        return default
    text = str(value).strip().replace(",", ".")
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def _to_int01(value):
    if value is None:
        return None
    t = str(value).strip().lower()
    if t in {"1", "true", "t", "sim", "s", "yes", "y"}:
        return 1
    if t in {"0", "false", "f", "não", "nao", "n", "no"}:
        return 0
    return None


def parse_input(raw):
    text = raw.strip()
    if not text or "<<<DADOS_PLANILHA_AQUI>>>" in text:
        return [], ["Entrada sem dados reais: placeholder detectado."], "unknown"

    # Try JSON first
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "alunos" in data and isinstance(data["alunos"], list):
            rows = []
            for aluno in data["alunos"]:
                if isinstance(aluno, dict) and "questoes" in aluno:
                    base = {k: v for k, v in aluno.items() if k != "questoes"}
                    for q in aluno["questoes"]:
                        row = {}
                        row.update(base)
                        row.update(q)
                        rows.append(row)
                elif isinstance(aluno, dict):
                    rows.append(aluno)
            return rows, [], "json"
        if isinstance(data, list):
            return data, [], "json"
        if isinstance(data, dict):
            return [data], [], "json"
    except json.JSONDecodeError:
        pass

    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines:
        return [], ["Entrada vazia após limpeza."], "unknown"

    # Strip wrappers like <<< >>>
    if lines[0].startswith("<<<") and lines[-1].endswith(">>>"):
        lines = lines[1:-1]

    sample = "\n".join(lines[:2])
    delimiter = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO("\n".join(lines)), delimiter=delimiter)
    rows = list(reader)
    return rows, [], "csv"


def resolve_columns(rows):
    aliases = {
        "aluno_id": ["aluno_id", "id_aluno"],
        "aluno_nome": ["aluno_nome", "nome_aluno", "aluno"],
        "simulado_id": ["simulado_id", "prova_id"],
        "data": ["data", "data_prova"],
        "questao_id": ["questao_id", "questao", "id_questao"],
        "competencia": ["competencia", "capacidade"],
        "conhecimento": ["conhecimento", "conteudo", "habilidade"],
        "bloom": ["bloom", "dificuldade", "nivel"],
        "resposta_aluno": ["resposta_aluno", "resposta"],
        "gabarito": ["gabarito", "resposta_correta"],
        "acertou": ["acertou", "correto"],
        "peso": ["peso"],
    }

    keys = set()
    for r in rows:
        keys.update(r.keys())

    mapping = {}
    for canonical, options in aliases.items():
        for o in options:
            if o in keys:
                mapping[canonical] = o
                break
    return mapping


def group_by_student(rows, mapping):
    grouped = defaultdict(list)
    for r in rows:
        aluno_id = _norm(r.get(mapping.get("aluno_id", "")))
        aluno_nome = _norm(r.get(mapping.get("aluno_nome", "")))
        key = aluno_id or aluno_nome or "ALUNO_UNICO"
        grouped[key].append(r)
    return grouped


def calc_student(rows, mapping):
    alerts = []
    missing = [k for k in ["questao_id", "competencia", "resposta_aluno", "gabarito"] if k not in mapping]
    if missing:
        alerts.append(f"Colunas ausentes inferidas/assumidas: {', '.join(missing)}")

    first = rows[0] if rows else {}
    aluno_id = _norm(first.get(mapping.get("aluno_id", ""))) or None
    aluno_nome = _norm(first.get(mapping.get("aluno_nome", ""))) or None
    simulado_id = _norm(first.get(mapping.get("simulado_id", ""))) or None
    data = _norm(first.get(mapping.get("data", ""))) or datetime.utcnow().strftime("%Y-%m-%d")
    if "data" not in mapping:
        alerts.append("Data ausente: preenchida com data atual UTC.")

    comp_data = defaultdict(list)
    total_acertos = 0
    total_peso = 0.0
    total_acerto_peso = 0.0

    for r in rows:
        comp = _norm(r.get(mapping.get("competencia", ""))) or "Competência não informada"
        conhecimento = _norm(r.get(mapping.get("conhecimento", ""))) or "Conhecimento não informado"
        bloom = _norm(r.get(mapping.get("bloom", "")))
        if not bloom and "bloom" not in mapping:
            bloom = "Não informado"

        if "peso" in mapping:
            peso = _to_float(r.get(mapping["peso"]), default=1.0)
        else:
            if bloom:
                peso = BLOOM_PESOS.get(bloom.strip().lower(), 1.0)
                if bloom.strip().lower() not in BLOOM_PESOS:
                    alerts.append(f"Bloom/dificuldade '{bloom}' não mapeado: peso 1.0 aplicado.")
            else:
                peso = 1.0
                alerts.append("Bloom ausente: peso 1.0 aplicado.")

        acertou = None
        if "acertou" in mapping:
            acertou = _to_int01(r.get(mapping["acertou"]))
        if acertou is None:
            ra = _norm(r.get(mapping.get("resposta_aluno", "")))
            gb = _norm(r.get(mapping.get("gabarito", "")))
            acertou = 1 if ra == gb and gb != "" else 0

        total_acertos += acertou
        total_peso += peso
        total_acerto_peso += acertou * peso

        comp_data[comp].append({
            "acertou": acertou,
            "peso": peso,
            "bloom": bloom or "Não informado",
            "conhecimento": conhecimento,
        })

    total_q = len(rows)
    acuracia_geral = (total_acertos / total_q) if total_q else 0.0
    acuracia_ponderada = (total_acerto_peso / total_peso) if total_peso else 0.0

    diag = []
    fortes, atencao, criticas = 0, 0, 0
    prioridade = []

    for comp, items in comp_data.items():
        tq = len(items)
        ac = sum(i["acertou"] for i in items)
        peso_sum = sum(i["peso"] for i in items)
        ac_peso = sum(i["acertou"] * i["peso"] for i in items)
        acu = ac / tq if tq else 0.0
        acu_p = ac_peso / peso_sum if peso_sum else 0.0

        bloom_dist = dict(Counter(i["bloom"] for i in items))
        by_con = defaultdict(list)
        for i in items:
            by_con[i["conhecimento"]].append(i["acertou"])
        con_rates = []
        for k, vals in by_con.items():
            con_rates.append((k, sum(vals) / len(vals), len(vals)))
        con_rates.sort(key=lambda x: (x[1], x[2], x[0]))
        deficits = [x[0] for x in con_rates[:3]] if con_rates else []

        if tq < 3:
            nivel = "Amostra insuficiente"
        elif acu_p >= 0.75:
            nivel = "Forte"
            fortes += 1
        elif acu_p >= 0.55:
            nivel = "Atenção"
            atencao += 1
        else:
            nivel = "Crítico"
            criticas += 1

        erros = []
        if deficits:
            erros.append(f"Maior concentração de erro em: {', '.join(deficits[:2])}.")
        if "Difícil" in bloom_dist or "Difícil" in [b for b in bloom_dist.keys()]:
            erros.append("Queda de desempenho em itens de maior dificuldade.")
        if tq < 3:
            erros.append("Poucas evidências para padrão robusto.")

        recs = [
            "Revisar conceitos-base com 3 questões graduadas.",
            "Aplicar correção comentada focando justificativa do gabarito.",
        ]

        diag.append({
            "competencia": comp,
            "total_questoes": tq,
            "acertos": ac,
            "acuracia": round(acu, 4),
            "acuracia_ponderada": round(acu_p, 4),
            "nivel": nivel,
            "distribuicao_bloom": bloom_dist,
            "principais_conhecimentos_deficitarios": deficits,
            "padroes_de_erro": erros[:3],
            "recomendacoes_imediatas": recs,
        })

        prioridade.append((comp, acu_p, peso_sum, tq))

    prioridade.sort(key=lambda x: (x[1], -x[2], -x[3]))
    focos = [p[0] for p in prioridade] or ["Competência geral"]

    plano = []
    for dia in range(1, 8):
        comp = focos[(dia - 1) % len(focos)]
        comp_diag = next((d for d in diag if d["competencia"] == comp), None)
        foco_con = "Revisão geral"
        if comp_diag and comp_diag["principais_conhecimentos_deficitarios"]:
            foco_con = comp_diag["principais_conhecimentos_deficitarios"][0]
        plano.append({
            "dia": dia,
            "foco_competencia": comp,
            "foco_conhecimento": foco_con,
            "objetivo": "Elevar acurácia ponderada com prática direcionada.",
            "atividades": [
                "Revisão ativa de teoria (flashcards/resumo).",
                "Bloco de 8 a 12 questões focadas.",
                "Correção com registro do tipo de erro.",
            ],
            "criterio_de_sucesso": "Atingir >=70% de acerto no bloco do dia.",
            "tempo_estimado_minutos": 50,
        })

    dist_bloom_por_comp = {d["competencia"]: d["distribuicao_bloom"] for d in diag}

    acoes_instrutor = [
        "Formar grupo de reforço para competências em nível Crítico.",
        "Aplicar miniavaliação diagnóstica ao final do dia 4.",
        "Fazer devolutiva individual com meta numérica de acurácia ponderada.",
        "Usar rubrica de erro (conceitual, leitura, distração) na correção.",
    ]

    forte_nome = next((d["competencia"] for d in diag if d["nivel"] == "Forte"), "seu desempenho geral")
    fraca_nome = next((d["competencia"] for d in diag if d["nivel"] in {"Crítico", "Atenção"}), "pontos específicos")

    return {
        "summary": {
            "aluno_id": aluno_id,
            "aluno_nome": aluno_nome,
            "simulado_id": simulado_id,
            "data": data,
            "total_questoes": total_q,
            "acertos": total_acertos,
            "acuracia_geral": round(acuracia_geral, 4),
            "acuracia_ponderada": round(acuracia_ponderada, 4),
            "competencias_fortes": fortes,
            "competencias_atencao": atencao,
            "competencias_criticas": criticas,
            "alertas_dados": sorted(set(alerts)),
        },
        "diagnostico_por_competencia": diag,
        "plano_de_estudos_7_dias": plano,
        "acoes_para_o_instrutor": acoes_instrutor,
        "metricas_para_dashboard": {
            "labels_competencias": [d["competencia"] for d in diag],
            "valores_acuracia_ponderada": [d["acuracia_ponderada"] for d in diag],
            "valores_total_questoes": [d["total_questoes"] for d in diag],
            "distribuicao_bloom_por_competencia": dist_bloom_por_comp,
        },
        "mensagem_para_o_aluno": (
            f"Você foi bem em {forte_nome}. "
            f"Precisamos melhorar em {fraca_nome} com prática orientada. "
            f"Próximo passo: seguir o plano de 7 dias e monitorar sua acurácia ponderada diariamente."
        ),
    }


def main():
    raw = sys.stdin.read()
    rows, parse_alerts, _fmt = parse_input(raw)
    if not rows:
        output = {
            "aluno": {
                "summary": {
                    "aluno_id": None,
                    "aluno_nome": None,
                    "simulado_id": None,
                    "data": datetime.utcnow().strftime("%Y-%m-%d"),
                    "total_questoes": 0,
                    "acertos": 0,
                    "acuracia_geral": 0.0,
                    "acuracia_ponderada": 0.0,
                    "competencias_fortes": 0,
                    "competencias_atencao": 0,
                    "competencias_criticas": 0,
                    "alertas_dados": parse_alerts or ["Nenhum dado de entrada processável."],
                },
                "diagnostico_por_competencia": [],
                "plano_de_estudos_7_dias": [
                    {
                        "dia": d,
                        "foco_competencia": "Sem dados",
                        "foco_conhecimento": "Sem dados",
                        "objetivo": "Aguardar dados válidos para diagnóstico.",
                        "atividades": ["Inserir planilha válida com questões do simulado."],
                        "criterio_de_sucesso": "Dados carregados com sucesso.",
                        "tempo_estimado_minutos": 10,
                    }
                    for d in range(1, 8)
                ],
                "acoes_para_o_instrutor": ["Validar template de dados e reenviar arquivo completo."],
                "metricas_para_dashboard": {
                    "labels_competencias": [],
                    "valores_acuracia_ponderada": [],
                    "valores_total_questoes": [],
                    "distribuicao_bloom_por_competencia": {},
                },
                "mensagem_para_o_aluno": "Recebemos um arquivo sem dados válidos; vamos corrigir isso e gerar seu plano personalizado.",
            }
        }
        print(json.dumps(output, ensure_ascii=False))
        return

    mapping = resolve_columns(rows)
    groups = group_by_student(rows, mapping)
    alunos = []
    for _key, rs in groups.items():
        aluno = calc_student(rs, mapping)
        aluno["summary"]["alertas_dados"].extend(parse_alerts)
        aluno["summary"]["alertas_dados"] = sorted(set(aluno["summary"]["alertas_dados"]))
        alunos.append(aluno)

    if len(alunos) == 1:
        print(json.dumps({"aluno": alunos[0]}, ensure_ascii=False))
    else:
        print(json.dumps({"alunos": alunos}, ensure_ascii=False))


if __name__ == "__main__":
    main()
