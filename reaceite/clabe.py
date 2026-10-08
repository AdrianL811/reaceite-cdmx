"""CLABE (Clave Bancaria Estandarizada): 18 dígitos, el último es de control.

Dígito de control: cada uno de los primeros 17 dígitos se multiplica por los pesos 3, 7, 1
(repetidos); de cada producto se toma el módulo 10, se suman, y el control es
(10 - suma mod 10) mod 10. En el piloto todas las cuentas son simuladas (banco 999).
"""
PESOS = (3, 7, 1)
BANCO_SIMULADO = "999"
PLAZA_CDMX = "180"


def digito_control(primeros17):
    suma = sum((int(c) * PESOS[i % 3]) % 10 for i, c in enumerate(primeros17))
    return (10 - suma % 10) % 10


def es_valida(clabe):
    return (
        isinstance(clabe, str)
        and len(clabe) == 18
        and clabe.isdigit()
        and int(clabe[17]) == digito_control(clabe[:17])
    )


def simulada(numero):
    base = f"{BANCO_SIMULADO}{PLAZA_CDMX}{numero:011d}"
    return base + str(digito_control(base))


def enmascarar(clabe):
    return f"terminación {clabe[-4:]}"
