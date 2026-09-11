import unicodedata
from difflib import SequenceMatcher


def _remover_acentos(texto: str) -> str:
    nfkd = unicodedata.normalize("NFKD", texto)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _similaridade_nome(nome1: str, nome2: str) -> float:
    """Retorna a similaridade entre dois nomes (0.0 a 1.0)."""
    if not nome1 or not nome2:
        return 0.0
    n1 = _remover_acentos(str(nome1)).lower().strip()
    n2 = _remover_acentos(str(nome2)).lower().strip()
    return SequenceMatcher(None, n1, n2).ratio()


NOME_1 = "JOEL FELIPE DOS SANTOS"
NOME_2 = "Gislaine Felipe dos Santos"

if __name__ == "__main__":
    score = _similaridade_nome(NOME_1, NOME_2)
    print(f"Nome 1: {NOME_1}")
    print(f"Nome 2: {NOME_2}")
    print(f"Similaridade: {score:.4f} ({score*100:.1f}%)")
