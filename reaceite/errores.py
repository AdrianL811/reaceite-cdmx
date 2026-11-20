"""Error de regla de negocio: lleva el mensaje para la persona, un código para el programa y el estado HTTP."""


class ErrorNegocio(Exception):
    def __init__(self, mensaje, codigo="invalido", http=400, extra=None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo
        self.http = http
        self.extra = extra or {}
