"""
SQL Escape Utilities - Funcoes para escapar caracteres especiais em queries.

Criado em: 11/03/2026 (Auditoria de Seguranca)

Contexto:
    Queries com .ilike() no Supabase/PostgreSQL interpretam % e _ como
    wildcards. Se o input do usuario contem esses caracteres, pode
    causar pattern matching nao intencional (NoSQL Injection).

Uso:
    from app.core.utils.sql_escape import escape_ilike_pattern

    phone_escaped = escape_ilike_pattern(phone_suffix)
    result = supabase.table("leads").select("*").ilike("remotejid", f"%{phone_escaped}%")
"""


def escape_ilike_pattern(pattern: str) -> str:
    """
    Escapa caracteres especiais do PostgreSQL ILIKE para busca literal.

    Caracteres escapados:
    - \\ (backslash) -> \\\\ (deve ser primeiro para nao re-escapar)
    - % (percent) -> \\%
    - _ (underscore) -> \\_

    Args:
        pattern: String a ser usada em query .ilike()

    Returns:
        String com wildcards escapados para busca literal

    Examples:
        >>> escape_ilike_pattern("999_9999")
        '999\\_9999'
        >>> escape_ilike_pattern("100%")
        '100\\%'
        >>> escape_ilike_pattern("5511987654321")
        '5511987654321'
    """
    if not pattern:
        return pattern

    # Ordem importa: escapar backslash primeiro
    result = pattern.replace("\\", "\\\\")
    result = result.replace("%", "\\%")
    result = result.replace("_", "\\_")

    return result
