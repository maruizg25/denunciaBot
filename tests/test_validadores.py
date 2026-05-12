"""
Tests de los validadores puros del flujo conversacional.

No requieren BD, Redis ni Meta API. Solo funciones puras.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from app.conversacion.mensajes import (
    BTN_ID_ACEPTAR,
    BTN_ID_CANCELAR,
    BTN_ID_CONFIRMAR,
    BTN_ID_EDITAR,
    BTN_ID_NO,
    BTN_ID_RECHAZAR,
    BTN_ID_SI,
)
from app.conversacion.validadores import (
    es_comando_cancelar,
    es_indicador_no_tengo_mas,
    normalizar,
    validar_aceptacion,
    validar_confirmacion,
    validar_denuncia_previa,
    validar_descripcion,
    validar_entidad_previa,
    validar_evidencia,
    validar_fecha,
    validar_institucion,
    validar_involucrados,
    validar_perjuicio,
)


# =========================================================================
# normalizar
# =========================================================================

class TestNormalizar:
    @pytest.mark.parametrize(
        "entrada,esperado",
        [
            ("Sí", "si"),
            ("SÍ", "si"),
            ("  sí  ", "si"),
            ("Mañana", "manana"),
            ("Acción", "accion"),
            ("", ""),
            ("HOLA MUNDO", "hola mundo"),
        ],
    )
    def test_quita_tildes_y_normaliza(self, entrada: str, esperado: str) -> None:
        assert normalizar(entrada) == esperado


# =========================================================================
# Comando cancelar
# =========================================================================

class TestCancelar:
    @pytest.mark.parametrize("texto", ["cancelar", "CANCELAR", "cancelo", "salir", "fin"])
    def test_texto_cancela(self, texto: str) -> None:
        assert es_comando_cancelar(texto) is True

    def test_boton_cancelar(self) -> None:
        assert es_comando_cancelar(None, boton_id=BTN_ID_CANCELAR) is True

    def test_boton_rechazar_tambien_cancela(self) -> None:
        assert es_comando_cancelar(None, boton_id=BTN_ID_RECHAZAR) is True

    @pytest.mark.parametrize("texto", ["hola", "continuar", "", None])
    def test_no_cancela(self, texto: str | None) -> None:
        assert es_comando_cancelar(texto) is False


# =========================================================================
# S2 — Aceptación
# =========================================================================

class TestAceptacion:
    @pytest.mark.parametrize("texto", ["sí", "si", "Yes", "ok", "claro", "acepto", "1", "y"])
    def test_si_variantes(self, texto: str) -> None:
        r = validar_aceptacion(texto)
        assert r.valido and r.valor_normalizado == "SI"

    @pytest.mark.parametrize("texto", ["no", "NO", "No acepto", "negativo", "2", "n"])
    def test_no_variantes(self, texto: str) -> None:
        r = validar_aceptacion(texto)
        assert r.valido and r.valor_normalizado == "NO"

    def test_boton_aceptar(self) -> None:
        r = validar_aceptacion(None, boton_id=BTN_ID_ACEPTAR)
        assert r.valido and r.valor_normalizado == "SI"

    def test_boton_rechazar(self) -> None:
        r = validar_aceptacion(None, boton_id=BTN_ID_RECHAZAR)
        assert r.valido and r.valor_normalizado == "NO"

    @pytest.mark.parametrize("texto", ["quizás", "", "blablabla", "tal vez"])
    def test_no_reconocido(self, texto: str) -> None:
        r = validar_aceptacion(texto)
        assert not r.valido and r.motivo


# =========================================================================
# S3 — Institución
# =========================================================================

class TestInstitucion:
    def test_valida(self) -> None:
        r = validar_institucion("Ministerio de Salud Pública")
        assert r.valido and r.valor_normalizado == "Ministerio de Salud Pública"

    def test_recorta_espacios(self) -> None:
        r = validar_institucion("  Ministerio  ")
        assert r.valido and r.valor_normalizado == "Ministerio"

    @pytest.mark.parametrize("texto", ["", "  ", "ab", "X"])
    def test_muy_corta(self, texto: str) -> None:
        r = validar_institucion(texto)
        assert not r.valido
        assert "menos" in (r.motivo or "").lower() or "vacío" in (r.motivo or "").lower() or "texto" in (r.motivo or "").lower()

    def test_demasiado_larga(self) -> None:
        r = validar_institucion("X" * 201)
        assert not r.valido
        assert "200" in (r.motivo or "")


# =========================================================================
# S4 — Descripción
# =========================================================================

class TestDescripcion:
    def test_valida(self) -> None:
        texto = "Descripción detallada de los hechos con datos relevantes."
        r = validar_descripcion(texto)
        assert r.valido

    @pytest.mark.parametrize("texto", ["corta", "X" * 29])
    def test_demasiado_corta(self, texto: str) -> None:
        r = validar_descripcion(texto)
        assert not r.valido

    def test_demasiado_larga(self) -> None:
        r = validar_descripcion("X" * 2001)
        assert not r.valido

    def test_limite_inferior(self) -> None:
        r = validar_descripcion("X" * 30)
        assert r.valido

    def test_limite_superior(self) -> None:
        r = validar_descripcion("X" * 2000)
        assert r.valido


# =========================================================================
# S5 — Fecha
# =========================================================================

class TestFecha:
    def test_dmy_valida(self) -> None:
        r = validar_fecha("15/03/2025")
        assert r.valido and r.valor_normalizado == "15/03/2025"

    def test_dmy_con_guiones(self) -> None:
        r = validar_fecha("15-03-2025")
        assert r.valido and r.valor_normalizado == "15/03/2025"

    def test_mes_y_anio(self) -> None:
        r = validar_fecha("03/2025")
        assert r.valido and r.valor_normalizado == "03/2025"

    def test_solo_anio(self) -> None:
        r = validar_fecha("2025")
        assert r.valido and r.valor_normalizado == "2025"

    @pytest.mark.parametrize("texto", ["no recuerdo", "No me acuerdo", "OLVIDÉ", "no sé"])
    def test_no_recuerdo(self, texto: str) -> None:
        r = validar_fecha(texto)
        assert r.valido and r.valor_normalizado == "No recuerdo"

    def test_fecha_futura_rechazada(self) -> None:
        manana = date.today() + timedelta(days=1)
        r = validar_fecha(manana.strftime("%d/%m/%Y"))
        assert not r.valido
        assert "futura" in (r.motivo or "").lower()

    def test_anio_demasiado_antiguo(self) -> None:
        r = validar_fecha("1899")
        assert not r.valido

    def test_fecha_inexistente(self) -> None:
        r = validar_fecha("31/02/2025")  # febrero no tiene 31
        assert not r.valido

    def test_mes_invalido(self) -> None:
        r = validar_fecha("13/2025")
        assert not r.valido

    @pytest.mark.parametrize("texto", ["abc", "32/13/2025", "hola"])
    def test_formato_irreconocible(self, texto: str) -> None:
        r = validar_fecha(texto)
        assert not r.valido


# =========================================================================
# S6 — Involucrados (opcional)
# =========================================================================

class TestInvolucrados:
    def test_texto_libre(self) -> None:
        r = validar_involucrados("Juan Pérez, director")
        assert r.valido and r.valor_normalizado == "Juan Pérez, director"

    @pytest.mark.parametrize("texto", ["no conozco", "Prefiero no decir", "ninguno", "N/A"])
    def test_no_conozco(self, texto: str) -> None:
        r = validar_involucrados(texto)
        assert r.valido and r.valor_normalizado is None

    def test_vacio(self) -> None:
        r = validar_involucrados("")
        assert r.valido and r.valor_normalizado is None


# =========================================================================
# S7 — Perjuicio (opcional)
# =========================================================================

class TestPerjuicio:
    def test_texto_libre(self) -> None:
        r = validar_perjuicio("aprox 50000 USD")
        assert r.valido and r.valor_normalizado == "aprox 50000 USD"

    @pytest.mark.parametrize("texto", ["no aplica", "No sé", "ninguno", "0"])
    def test_no_aplica(self, texto: str) -> None:
        r = validar_perjuicio(texto)
        assert r.valido and r.valor_normalizado is None


# =========================================================================
# S8 — Denuncia previa
# =========================================================================

class TestDenunciaPrevia:
    @pytest.mark.parametrize("texto,esperado", [("sí", "SI"), ("no", "NO")])
    def test_si_no(self, texto: str, esperado: str) -> None:
        r = validar_denuncia_previa(texto)
        assert r.valido and r.valor_normalizado == esperado

    def test_boton_si(self) -> None:
        r = validar_denuncia_previa(None, boton_id=BTN_ID_SI)
        assert r.valido and r.valor_normalizado == "SI"

    def test_boton_no(self) -> None:
        r = validar_denuncia_previa(None, boton_id=BTN_ID_NO)
        assert r.valido and r.valor_normalizado == "NO"

    def test_no_reconocido(self) -> None:
        r = validar_denuncia_previa("quizás")
        assert not r.valido


class TestEntidadPrevia:
    def test_valida(self) -> None:
        r = validar_entidad_previa("Fiscalía General del Estado")
        assert r.valido

    def test_vacia(self) -> None:
        r = validar_entidad_previa("")
        assert not r.valido

    def test_demasiado_corta(self) -> None:
        r = validar_entidad_previa("ab")
        assert not r.valido


# =========================================================================
# S9 — Evidencia
# =========================================================================

class TestEvidencia:
    PERMITIDOS = frozenset({"application/pdf", "image/jpeg", "image/png"})
    MAX = 10 * 1024 * 1024  # 10 MB

    def test_pdf_valido(self) -> None:
        r = validar_evidencia(
            tamanio_bytes=500_000, mime="application/pdf",
            mimes_permitidos=self.PERMITIDOS, tamanio_max_bytes=self.MAX,
        )
        assert r.valido and r.mime_normalizado == "application/pdf"

    def test_mime_no_permitido(self) -> None:
        r = validar_evidencia(
            tamanio_bytes=500_000, mime="application/zip",
            mimes_permitidos=self.PERMITIDOS, tamanio_max_bytes=self.MAX,
        )
        assert not r.valido and r.motivo == "tipo_no_permitido"

    def test_archivo_vacio(self) -> None:
        r = validar_evidencia(
            tamanio_bytes=0, mime="application/pdf",
            mimes_permitidos=self.PERMITIDOS, tamanio_max_bytes=self.MAX,
        )
        assert not r.valido and r.motivo == "archivo_vacio"

    def test_demasiado_grande(self) -> None:
        r = validar_evidencia(
            tamanio_bytes=15 * 1024 * 1024, mime="application/pdf",
            mimes_permitidos=self.PERMITIDOS, tamanio_max_bytes=self.MAX,
        )
        assert not r.valido and r.motivo == "tamanio_excedido"

    def test_mime_case_insensitive(self) -> None:
        r = validar_evidencia(
            tamanio_bytes=500_000, mime="APPLICATION/PDF",
            mimes_permitidos=self.PERMITIDOS, tamanio_max_bytes=self.MAX,
        )
        assert r.valido and r.mime_normalizado == "application/pdf"


class TestIndicadorNoTengoMas:
    @pytest.mark.parametrize("texto", ["no tengo", "ninguno", "ya está", "listo", "no"])
    def test_si_termina(self, texto: str) -> None:
        assert es_indicador_no_tengo_mas(texto) is True

    @pytest.mark.parametrize("texto", ["espera", "otro", ""])
    def test_no_termina(self, texto: str) -> None:
        assert es_indicador_no_tengo_mas(texto) is False


# =========================================================================
# S10 — Confirmación
# =========================================================================

class TestConfirmacion:
    @pytest.mark.parametrize("boton,esperado", [
        (BTN_ID_CONFIRMAR, "confirmar"),
        (BTN_ID_EDITAR, "editar"),
        (BTN_ID_CANCELAR, "cancelar"),
    ])
    def test_botones(self, boton: str, esperado: str) -> None:
        r = validar_confirmacion(None, boton_id=boton)
        assert r.valido and r.valor_normalizado == esperado

    @pytest.mark.parametrize("texto,esperado", [
        ("confirmar", "confirmar"),
        ("confirmo", "confirmar"),
        ("editar", "editar"),
        ("modificar", "editar"),
        ("cancelar", "cancelar"),
        ("salir", "cancelar"),
    ])
    def test_textos(self, texto: str, esperado: str) -> None:
        r = validar_confirmacion(texto)
        assert r.valido and r.valor_normalizado == esperado

    def test_no_reconocido(self) -> None:
        r = validar_confirmacion("blablabla")
        assert not r.valido
