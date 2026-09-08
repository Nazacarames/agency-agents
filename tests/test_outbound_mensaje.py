"""Las guardas del mensaje que sale, probadas con los mails REALES de la casilla.

Los cuerpos de abajo salieron tal cual el 2026-09-08 desde Ventas@. Los tres
defectos que tenian --se presentaban, eran un bloque de texto sin un solo salto de
linea, y algunos inventaban casos de exito-- son lo que estas guardas atajan.
"""
import sys
import pathlib

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.agents.outbound import (_INVENTA_CASO, _dar_formato, _limpiar_subject,
                                 _sin_presentacion)

FIRMA = "Nazareno Carames"

# Reales, copiados de los enviados.
REAL_QUIPA = ("Hola, soy Nazareno de Automiq. En adhesivos industriales el comprador "
              "tecnico manda la consulta cuando cierra su jornada y espera respuesta con "
              "ficha tecnica, no con \"le llamamos manana\". Un agente de IA atiende al "
              "instante, le pasa la ficha del adhesivo segun sustrato y volumen, y te avisa "
              "cuando es cliente nuevo o pedido grande. Te arme un ejemplo para QUIPA: 20 "
              "segundos aca https://app.automiq.agency/d/25e1134286. Lo miramos 15 min? "
              "Saludos, Nazareno Carames")
REAL_EFIPLAST = ("Hola, soy Nazareno de Automiq. Una fabrica B2B similar a Efiplast recupero "
                 "cerca del 30% de consultas tecnicas fuera de horario con el agente "
                 "automatico. Te paso el ejemplo aplicado a Efiplast? Saludos, Nazareno Carames")
REAL_POLIPACK = ("Hola Mauro, soy Nazareno de Automiq. Una distribuidora regional similar a "
                 "Polipack recupero cerca del 30% de pedidos que quedaban en visto con el "
                 "agente de WhatsApp. Te paso ese ejemplo aplicado a Polipack? Saludos, "
                 "Nazareno Carames")


def test_frena_el_caso_de_exito_inventado():
    """No tenemos ninguna 'fabrica similar' que recupero 30%. Ese mail no sale."""
    assert _INVENTA_CASO.search(REAL_EFIPLAST), "el de Efiplast inventaba un caso"
    assert _INVENTA_CASO.search(REAL_POLIPACK), "el de Polipack inventaba un caso"
    assert _INVENTA_CASO.search("otro cliente del rubro le subio un 25%")
    assert _INVENTA_CASO.search("una pyme parecida a la tuya mejoro 40 %")
    # Y no puede frenar un mail honesto.
    assert not _INVENTA_CASO.search(REAL_QUIPA)
    assert not _INVENTA_CASO.search(
        "Te armo uno con los productos de Polipack y te lo mando?")
    assert not _INVENTA_CASO.search(
        "En CLAMEVET el agente contesta las consultas de los socios.")


def test_saca_la_presentacion_del_arranque():
    """'Hola, soy Nazareno de Automiq.' abria casi todos los mails enviados."""
    fuera = _sin_presentacion(REAL_QUIPA)
    assert not fuera.lower().startswith("hola, soy nazareno")
    assert fuera.startswith("Hola,"), "el saludo se queda, la presentacion se va"
    assert "En adhesivos industriales" in fuera
    # Con nombre propio tambien.
    assert "soy Nazareno" not in _sin_presentacion(REAL_POLIPACK)
    assert _sin_presentacion(REAL_POLIPACK).startswith("Hola Mauro,")
    # Un cuerpo que ya arranca bien no se toca.
    ok = "Hola,\n\nUstedes venden maquinaria.\n\nSaludos,\nNazareno Carames"
    assert _sin_presentacion(ok) == ok


def test_le_da_forma_de_mail_al_bloque():
    """Todos salian en una sola linea con la firma pegada a la ultima oracion."""
    assert "\n" not in REAL_QUIPA, "asi salio de verdad: cero saltos de linea"
    out = _dar_formato(_sin_presentacion(REAL_QUIPA), FIRMA)
    lineas = out.split("\n")
    assert lineas[0] == "Hola,", f"el saludo va SOLO en su renglon, no {lineas[0]!r}"
    assert "En adhesivos industriales" in lineas[2], "el cuerpo arranca en su propio bloque"
    assert out.endswith(f"Saludos,\n{FIRMA}"), "la firma va sola, en dos lineas"
    assert "\n\n" in out
    assert lineas[1] == "", "linea en blanco despues del saludo"
    assert len([p for p in out.split("\n\n") if p.strip()]) >= 3, "saludo + cuerpo + firma"
    # La firma no queda duplicada dentro del cuerpo.
    assert out.count(FIRMA) == 1


def test_respeta_el_nombre_en_el_saludo():
    out = _dar_formato(_sin_presentacion(REAL_POLIPACK), FIRMA)
    assert out.split("\n")[0] == "Hola Mauro,"


def test_no_toca_lo_que_ya_viene_bien():
    ya = "Hola,\n\nprimer bloque.\n\nsegundo bloque.\n\nSaludos,\nNazareno Carames"
    assert _dar_formato(ya, FIRMA) == ya


def test_limpia_el_subject_prohibido():
    """El prompt prohibia 'demo para' hacia semanas y seguia saliendo."""
    assert _limpiar_subject("demo para Castillo: consultas de propiedades en CABA") == \
        "consultas de propiedades en CABA"
    assert _limpiar_subject("Re: demo para Efiplast: pedidos 24/7") == "Re: pedidos 24/7"
    assert _limpiar_subject("Re: demo para Polipack") == "Re: Polipack"
    # Un asunto sano no se toca.
    assert _limpiar_subject("consulta tecnica de maquina a las 18 hs") == \
        "consulta tecnica de maquina a las 18 hs"
    assert _limpiar_subject("Re: la consulta de CABA del domingo") == \
        "Re: la consulta de CABA del domingo"


if __name__ == "__main__":
    for fn in (test_frena_el_caso_de_exito_inventado, test_saca_la_presentacion_del_arranque,
               test_le_da_forma_de_mail_al_bloque, test_respeta_el_nombre_en_el_saludo,
               test_no_toca_lo_que_ya_viene_bien, test_limpia_el_subject_prohibido):
        fn()
        print("OK", fn.__name__)
    print("\n--- antes y despues, con el mail real de QUIPA ---")
    print("\n[ANTES]\n" + REAL_QUIPA)
    print("\n[DESPUES]\n" + _dar_formato(_sin_presentacion(REAL_QUIPA), FIRMA))
