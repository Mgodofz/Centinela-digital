from ariadne import ObjectType, QueryType, MutationType, make_executable_schema
from database.bd import obtener_conexion

# 1. Definir el esquema (SDL)
type_defs = """
    type Reporte {
        id: Int!
        incidente: String!
        fecha: String
        nivel_riesgo: String
        prioridad: Int
        estatus_caso: String
        responsable: String
    }

    type Caso {
        id: Int!
        reporte_id: Int!
        responsable: String!
        estatus_caso: String
    }

    type Institucion {
        id: Int!
        nombre_institucion: String!
        especialidad: String!
        contacto: String!
    }

    type Comunicacion {
        id: Int!
        caso_id: Int!
        remitente: String!
        mensaje: String!
    }

    type Canalizacion {
        id: Int!
        reporte_id: Int!
        institucion_id: Int!
        nombre_institucion: String!
        fecha_canalizacion: String
    }

    type Estadisticas {
        total_reportes: Int
        total_usuarios: Int
        total_instituciones: Int
        cerrados: Int
    }

    type Query {
        reportes: [Reporte]
        reporte(id: Int!): Reporte
        casos: [Caso]
        instituciones: [Institucion]
        canalizaciones: [Canalizacion]
        mensajes(caso_id: Int!): [Comunicacion]
        estadisticas: Estadisticas
    }

    type Mutation {
        crear_reporte(incidente: String!, nivel_riesgo: String): Reporte
        crear_caso(reporte_id: Int!, responsable: String!, estatus_caso: String): Caso
    }
"""

# 2. Resolvers
query = QueryType()
mutation = MutationType()

def _iso(v):
    return v.isoformat() if hasattr(v, 'isoformat') else v

@query.field("reportes")
def resolve_reportes(*_):
    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute("""
                SELECT r.id, r.incidente, r.fecha, e.nivel_riesgo, e.prioridad, ca.estatus_caso, ca.responsable
                FROM reportes r
                LEFT JOIN evaluaciones e ON e.reporte_id=r.id
                LEFT JOIN casos ca ON ca.reporte_id=r.id
                ORDER BY r.id DESC
            """)
            return [{**r, 'fecha': _iso(r['fecha'])} for r in c.fetchall()]
    finally:
        conexion.close()

@query.field("reporte")
def resolve_reporte(*_, id):
    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute("""
                SELECT r.id, r.incidente, r.fecha, e.nivel_riesgo, e.prioridad, ca.estatus_caso, ca.responsable
                FROM reportes r
                LEFT JOIN evaluaciones e ON e.reporte_id=r.id
                LEFT JOIN casos ca ON ca.reporte_id=r.id
                WHERE r.id=%s
            """, (id,))
            r = c.fetchone()
            return {**r, 'fecha': _iso(r['fecha'])} if r else None
    finally:
        conexion.close()

@query.field("casos")
def resolve_casos(*_):
    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute("SELECT * FROM casos ORDER BY id DESC")
            return c.fetchall()
    finally:
        conexion.close()

@query.field("instituciones")
def resolve_instituciones(*_):
    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute("SELECT * FROM instituciones ORDER BY id DESC")
            return c.fetchall()
    finally:
        conexion.close()

@query.field("canalizaciones")
def resolve_canalizaciones(*_):
    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute("""
                SELECT ca.*, i.nombre_institucion
                FROM canalizaciones ca
                JOIN instituciones i ON i.id=ca.institucion_id
                ORDER BY ca.id DESC
            """)
            return [{**r, 'fecha_canalizacion': _iso(r['fecha_canalizacion'])} for r in c.fetchall()]
    finally:
        conexion.close()

@query.field("mensajes")
def resolve_mensajes(*_, caso_id):
    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute("SELECT * FROM comunicaciones WHERE caso_id=%s ORDER BY id", (caso_id,))
            return c.fetchall()
    finally:
        conexion.close()

@query.field("estadisticas")
def resolve_estadisticas(*_):
    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute("SELECT COUNT(*) AS t FROM reportes"); tr = c.fetchone()['t']
            c.execute("SELECT COUNT(*) AS t FROM usuarios"); tu = c.fetchone()['t']
            c.execute("SELECT COUNT(*) AS t FROM instituciones"); ti = c.fetchone()['t']
            c.execute("SELECT COUNT(*) AS t FROM casos WHERE estatus_caso='Cerrado'"); ce = c.fetchone()['t']
            return {"total_reportes": tr, "total_usuarios": tu, "total_instituciones": ti, "cerrados": ce}
    finally:
        conexion.close()

@mutation.field("crear_reporte")
def resolve_crear_reporte(*_, incidente, nivel_riesgo='Baja'):
    prioridad = {'Baja': 1, 'Media': 2, 'Alta': 3, 'Crítica': 4}.get(nivel_riesgo, 1)
    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute("INSERT INTO reportes (incidente) VALUES (%s)", (incidente,))
            rid = c.lastrowid
            c.execute("INSERT INTO evaluaciones (reporte_id, nivel_riesgo, prioridad) VALUES (%s,%s,%s)", (rid, nivel_riesgo, prioridad))
            conexion.commit()
        return {"id": rid, "incidente": incidente, "nivel_riesgo": nivel_riesgo, "prioridad": prioridad}
    finally:
        conexion.close()

@mutation.field("crear_caso")
def resolve_crear_caso(*_, reporte_id, responsable, estatus_caso='Abierto'):
    conexion = obtener_conexion()
    try:
        with conexion.cursor() as c:
            c.execute("INSERT INTO casos (reporte_id, responsable, estatus_caso) VALUES (%s,%s,%s)", (reporte_id, responsable, estatus_caso))
            cid = c.lastrowid
            conexion.commit()
        return {"id": cid, "reporte_id": reporte_id, "responsable": responsable, "estatus_caso": estatus_caso}
    finally:
        conexion.close()

# 3. Crear el esquema ejecutable (Ariadne nativo)
schema = make_executable_schema(type_defs, query, mutation)