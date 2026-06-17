import sqlite3
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DB_PATH

def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn

def create_tables(conn):
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS utilisateurs (
        id                 TEXT PRIMARY KEY,
        nom                TEXT NOT NULL,
        email              TEXT NOT NULL UNIQUE,
        mot_de_passe       TEXT NOT NULL,
        role               TEXT NOT NULL DEFAULT 'lecteur'
                               CHECK(role IN ('administrateur','lecteur')),
        actif              INTEGER NOT NULL DEFAULT 1,
        derniere_connexion TEXT,
        reset_token        TEXT,
        reset_token_exp    TEXT,
        cree_le            TEXT NOT NULL,
        modifie_le         TEXT NOT NULL
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sources (
        id                TEXT PRIMARY KEY,
        nom               TEXT NOT NULL,
        url               TEXT NOT NULL UNIQUE,
        type_source       TEXT NOT NULL DEFAULT 'rss'
                              CHECK(type_source IN ('rss','web','upload')),
        langue            TEXT NOT NULL DEFAULT 'fr'
                              CHECK(langue IN ('fr','en')),
        active            INTEGER NOT NULL DEFAULT 1,
        frequence_heures  INTEGER NOT NULL DEFAULT 168,
        derniere_collecte TEXT,
        cree_le           TEXT NOT NULL,
        cree_par          TEXT REFERENCES utilisateurs(id)
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS articles (
        id              TEXT PRIMARY KEY,
        source_id       TEXT NOT NULL REFERENCES sources(id),
        titre           TEXT NOT NULL,
        contenu         TEXT,
        resume          TEXT,
        url_original    TEXT NOT NULL,
        publie_le       TEXT,
        collecte_le     TEXT NOT NULL,
        langue          TEXT DEFAULT 'fr',
        est_doublon     INTEGER NOT NULL DEFAULT 0,
        indexe          INTEGER NOT NULL DEFAULT 0,
        qualite_contenu TEXT NOT NULL DEFAULT 'inconnu'
                        CHECK(qualite_contenu IN (
                            'complet','partiel','resume','inconnu','hors_perimetre'
                        ))
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS documents (
        id              TEXT PRIMARY KEY,
        nom_fichier     TEXT NOT NULL,
        chemin_stockage TEXT NOT NULL,
        type_doc        TEXT NOT NULL DEFAULT 'pdf'
                            CHECK(type_doc IN ('pdf','docx','txt','autre')),
        description     TEXT,
        uploade_par     TEXT REFERENCES utilisateurs(id),
        uploade_le      TEXT NOT NULL,
        indexe          INTEGER NOT NULL DEFAULT 0
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS chunks (
        id          TEXT PRIMARY KEY,
        article_id  TEXT REFERENCES articles(id),
        document_id TEXT REFERENCES documents(id),
        contenu     TEXT NOT NULL,
        position    INTEGER NOT NULL DEFAULT 0,
        indexe_le   TEXT,
        faiss_id    INTEGER
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS historique_actions_diif (
        id            TEXT PRIMARY KEY,
        titre         TEXT NOT NULL,
        description   TEXT NOT NULL,
        dimension     TEXT,
        zone          TEXT,
        date_action   TEXT NOT NULL,
        statut        TEXT DEFAULT 'réalisé'
                         CHECK(statut IN ('réalisé','en cours','planifié')),
        source_info   TEXT,
        cree_par      TEXT REFERENCES utilisateurs(id),
        cree_le       TEXT NOT NULL
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS reset_tokens (
        id         TEXT PRIMARY KEY,
        email      TEXT NOT NULL,
        token      TEXT NOT NULL UNIQUE,
        expire_le  TEXT NOT NULL,
        utilise    INTEGER NOT NULL DEFAULT 0,
        cree_le    TEXT NOT NULL
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_reset_token "
        "ON reset_tokens (token)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_reset_email "
        "ON reset_tokens (email)"
    )

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS classifications (
        id         TEXT PRIMARY KEY,
        chunk_id   TEXT NOT NULL REFERENCES chunks(id),
        dimension  TEXT,
        cible      TEXT,
        zone_cemac TEXT,
        score      REAL DEFAULT 0.0,
        classe_le  TEXT NOT NULL
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS suggestions (
        id            TEXT PRIMARY KEY,
        contenu       TEXT NOT NULL,
        dimension     TEXT,
        cible         TEXT,
        zone_cemac    TEXT,
        periode_debut TEXT,
        periode_fin   TEXT,
        cree_le       TEXT NOT NULL
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS mail_destinataires (
        id            TEXT PRIMARY KEY,
        adresse_email TEXT NOT NULL UNIQUE,
        nom           TEXT,
        active        INTEGER NOT NULL DEFAULT 1,
        ajoute_par    TEXT REFERENCES utilisateurs(id),
        ajoute_le     TEXT NOT NULL
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS mail_envois (
        id               TEXT PRIMARY KEY,
        envoye_le        TEXT NOT NULL,
        statut           TEXT NOT NULL DEFAULT 'envoye'
                             CHECK(statut IN ('envoye','echec','partiel')),
        nb_destinataires INTEGER DEFAULT 0,
        contenu_resume   TEXT,
        periode_debut    TEXT,
        periode_fin      TEXT
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS rapports (
        id             TEXT PRIMARY KEY,
        titre          TEXT NOT NULL,
        format         TEXT NOT NULL DEFAULT 'docx'
                           CHECK(format IN ('docx','pdf')),
        chemin_fichier TEXT NOT NULL,
        periode_debut  TEXT,
        periode_fin    TEXT,
        dimensions     TEXT,
        cibles         TEXT,
        zones          TEXT,
        genere_par     TEXT REFERENCES utilisateurs(id),
        genere_le      TEXT NOT NULL
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS notifications (
        id             TEXT PRIMARY KEY,
        utilisateur_id TEXT NOT NULL REFERENCES utilisateurs(id),
        message        TEXT NOT NULL,
        dimension      TEXT,
        lue            INTEGER NOT NULL DEFAULT 0,
        cree_le        TEXT NOT NULL
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS logs_activite (
        id             TEXT PRIMARY KEY,
        utilisateur_id TEXT REFERENCES utilisateurs(id),
        action         TEXT NOT NULL,
        entite_type    TEXT,
        entite_id      TEXT,
        detail         TEXT,
        ip_address     TEXT,
        horodatage     TEXT NOT NULL
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS parametres (
        cle        TEXT PRIMARY KEY,
        valeur     TEXT,
        modifie_le TEXT
    )""")

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS interactions_chatbot (
        id                   TEXT PRIMARY KEY,
        utilisateur_id       TEXT REFERENCES utilisateurs(id),
        requete_utilisateur  TEXT NOT NULL,
        requete_rag_utilisee TEXT,
        dimension_detectee   TEXT,
        chunks_recuperes     TEXT,
        reponse_generee      TEXT,
        sources_citees       TEXT,
        horodatage           TEXT NOT NULL
    )""")
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_interactions_horodatage "
        "ON interactions_chatbot (horodatage)"
    )

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS feedback_reponses (
        id             TEXT PRIMARY KEY,
        interaction_id TEXT REFERENCES interactions_chatbot(id),
        note           INTEGER NOT NULL CHECK(note IN (1, -1)),
        commentaire    TEXT,
        utilisateur_id TEXT REFERENCES utilisateurs(id),
        horodatage     TEXT NOT NULL
    )""")

    # ── Index de performance ──────────────────────────────────────────────
    # url_original UNIQUE : accélère la déduplication du scraping (url_existe)
    # et permet la dédup native via INSERT OR IGNORE.
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_articles_url "
        "ON articles(url_original)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_articles_source "
        "ON articles(source_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_article "
        "ON chunks(article_id)"
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_chunks_faiss "
        "ON chunks(faiss_id)"
    )

    conn.commit()
    print(f"[OK] Toutes les tables créées dans : {DB_PATH}")

def create_admin_default(conn):
    import uuid, bcrypt
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM utilisateurs WHERE role='administrateur'")
    if cursor.fetchone()[0] > 0:
        print("[INFO] Administrateur existant — création ignorée.")
        return
    admin_id = str(uuid.uuid4())
    now      = datetime.utcnow().isoformat()
    password = "Admin@DIIF2025"
    hashed   = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    cursor.execute("""
        INSERT INTO utilisateurs
            (id, nom, email, mot_de_passe, role, actif, cree_le, modifie_le)
        VALUES (?, ?, ?, ?, ?, 1, ?, ?)
    """, (admin_id, "Administrateur DIIF", "admin@beac.int",
          hashed, "administrateur", now, now))
    conn.commit()
    print("[OK] Compte administrateur créé :")
    print("     Email        : admin@beac.int")
    print("     Mot de passe : Admin@DIIF2025")
    print("     [!] Changez ce mot de passe après la première connexion.")

def create_sources_default(conn):
    import uuid
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sources")
    if cursor.fetchone()[0] > 0:
        print("[INFO] Sources existantes — insertion ignorée.")
        return
    now = datetime.utcnow().isoformat()
    sources = [
        ("CGAP",           "https://www.cgap.org",                      "web", "en"),
        ("FinDev Gateway", "https://www.findevgateway.org",             "rss", "en"),
        ("GSMA",           "https://www.gsma.com/newsroom",             "web", "en"),
        ("AFI Global",     "https://afi-global.org",                    "web", "en"),
        ("Agence Ecofin",  "https://www.agenceecofin.com/rss",          "rss", "fr"),
        ("Banque de France", "https://www.banque-france.fr",            "web", "fr"),
        ("BRI / BIS",      "https://www.bis.org",                       "rss", "en"),
        ("BEAC officiel",  "https://www.beac.int/",                     "web", "fr"),
    ]
    for nom, url, type_src, langue in sources:
        cursor.execute("""
            INSERT OR IGNORE INTO sources
                (id, nom, url, type_source, langue, active, frequence_heures, cree_le)
            VALUES (?, ?, ?, ?, ?, 1, 168, ?)
        """, (str(uuid.uuid4()), nom, url, type_src, langue, now))
    conn.commit()
    print(f"[OK] {len(sources)} sources insérées.")

if __name__ == "__main__":
    print("=" * 60)
    print("  Initialisation — Système de veille DIIF/BEAC")
    print("=" * 60)
    conn = get_connection()
    create_tables(conn)
    create_admin_default(conn)
    create_sources_default(conn)
    # Migration — ajoute qualite_contenu si base existante
    try:
        conn.execute(
            "ALTER TABLE articles ADD COLUMN qualite_contenu TEXT NOT NULL DEFAULT 'inconnu'"
        )
        print("[OK] Colonne qualite_contenu ajoutée.")
    except Exception:
        print("[INFO] Colonne qualite_contenu déjà présente.")
    # Migration — colonnes de classification (dimension / zone / cible)
    for col in ("dimension", "zone", "cible"):
        try:
            conn.execute(f"ALTER TABLE articles ADD COLUMN {col} TEXT")
            print(f"[OK] Colonne articles.{col} ajoutée.")
        except Exception:
            print(f"[INFO] Colonne articles.{col} déjà présente.")
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_articles_dimension "
            "ON articles(dimension)"
        )
    except Exception as e:
        print(f"[INFO] {e}")
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS historique_actions_diif (
                id            TEXT PRIMARY KEY,
                titre         TEXT NOT NULL,
                description   TEXT NOT NULL,
                dimension     TEXT,
                zone          TEXT,
                date_action   TEXT NOT NULL,
                statut        TEXT DEFAULT 'réalisé',
                source_info   TEXT,
                cree_par      TEXT,
                cree_le       TEXT NOT NULL
            )
        """)
        print("[OK] Table historique_actions_diif créée.")
    except Exception as e:
        print(f"[INFO] {e}")
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reset_tokens (
                id         TEXT PRIMARY KEY,
                email      TEXT NOT NULL,
                token      TEXT NOT NULL UNIQUE,
                expire_le  TEXT NOT NULL,
                utilise    INTEGER NOT NULL DEFAULT 0,
                cree_le    TEXT NOT NULL
            )
        """)
        print("[OK] Table reset_tokens créée.")
    except Exception as e:
        print(f"[INFO] {e}")
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS parametres (
                cle        TEXT PRIMARY KEY,
                valeur     TEXT,
                modifie_le TEXT
            )
        """)
        print("[OK] Table parametres créée.")
    except Exception as e:
        print(f"[INFO] {e}")
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS interactions_chatbot (
                id                   TEXT PRIMARY KEY,
                utilisateur_id       TEXT,
                requete_utilisateur  TEXT NOT NULL,
                requete_rag_utilisee TEXT,
                dimension_detectee   TEXT,
                chunks_recuperes     TEXT,
                reponse_generee      TEXT,
                sources_citees       TEXT,
                horodatage           TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_interactions_horodatage "
            "ON interactions_chatbot (horodatage)"
        )
        print("[OK] Table interactions_chatbot créée.")
    except Exception as e:
        print(f"[INFO] {e}")
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS feedback_reponses (
                id             TEXT PRIMARY KEY,
                interaction_id TEXT,
                note           INTEGER NOT NULL,
                commentaire    TEXT,
                utilisateur_id TEXT,
                horodatage     TEXT NOT NULL
            )
        """)
        print("[OK] Table feedback_reponses créée.")
    except Exception as e:
        print(f"[INFO] {e}")
    conn.close()
    print("=" * 60)
    print("  Base de données prête.")
    print("=" * 60)
