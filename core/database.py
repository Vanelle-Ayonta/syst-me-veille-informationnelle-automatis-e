import sqlite3
import os
import uuid
import json
from datetime import datetime
from contextlib import contextmanager
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import DB_PATH

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout=5000")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def now_iso():
    return datetime.utcnow().isoformat()

def new_id():
    return str(uuid.uuid4())

def get_utilisateur_by_email(email):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM utilisateurs WHERE email = ? AND actif = 1",
            (email,)
        ).fetchone()
        return dict(row) if row else None

def get_utilisateur_by_id(uid):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM utilisateurs WHERE id = ?", (uid,)
        ).fetchone()
        return dict(row) if row else None

def get_all_utilisateurs():
    with get_db() as conn:
        rows = conn.execute(
            "SELECT id, nom, email, role, actif, derniere_connexion, cree_le "
            "FROM utilisateurs ORDER BY cree_le DESC"
        ).fetchall()
        return [dict(r) for r in rows]

def create_utilisateur(nom, email, mot_de_passe_hash, role="lecteur"):
    uid = new_id()
    now = now_iso()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO utilisateurs
                (id, nom, email, mot_de_passe, role, actif, cree_le, modifie_le)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
        """, (uid, nom, email, mot_de_passe_hash, role, now, now))
    return uid

def update_derniere_connexion(uid):
    with get_db() as conn:
        conn.execute(
            "UPDATE utilisateurs SET derniere_connexion = ? WHERE id = ?",
            (now_iso(), uid)
        )

def update_utilisateur(uid, **kwargs):
    allowed = {"nom", "email", "role", "actif", "mot_de_passe"}
    fields  = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    fields["modifie_le"] = now_iso()
    sets   = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [uid]
    with get_db() as conn:
        conn.execute(f"UPDATE utilisateurs SET {sets} WHERE id = ?", values)

def set_reset_token(uid, token, expiry_iso):
    with get_db() as conn:
        conn.execute(
            "UPDATE utilisateurs SET reset_token=?, reset_token_exp=? WHERE id=?",
            (token, expiry_iso, uid)
        )

def get_utilisateur_by_reset_token(token):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM utilisateurs WHERE reset_token = ?", (token,)
        ).fetchone()
        return dict(row) if row else None

def clear_reset_token(uid):
    with get_db() as conn:
        conn.execute(
            "UPDATE utilisateurs "
            "SET reset_token=NULL, reset_token_exp=NULL WHERE id=?",
            (uid,)
        )

def log_action(utilisateur_id, action, entite_type=None,
               entite_id=None, detail=None, ip=None):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO logs_activite
                (id, utilisateur_id, action, entite_type, entite_id,
                 detail, ip_address, horodatage)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (new_id(), utilisateur_id, action, entite_type,
              entite_id, detail, ip, now_iso()))

def get_logs(limit=200, utilisateur_id=None):
    with get_db() as conn:
        if utilisateur_id:
            rows = conn.execute("""
                SELECT l.*, u.nom, u.email FROM logs_activite l
                LEFT JOIN utilisateurs u ON l.utilisateur_id = u.id
                WHERE l.utilisateur_id = ?
                ORDER BY l.horodatage DESC LIMIT ?
            """, (utilisateur_id, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT l.*, u.nom, u.email FROM logs_activite l
                LEFT JOIN utilisateurs u ON l.utilisateur_id = u.id
                ORDER BY l.horodatage DESC LIMIT ?
            """, (limit,)).fetchall()
        return [dict(r) for r in rows]

def get_all_sources(active_only=False):
    with get_db() as conn:
        q = "SELECT * FROM sources"
        if active_only:
            q += " WHERE active = 1"
        q += " ORDER BY nom"
        return [dict(r) for r in conn.execute(q).fetchall()]

def create_source(nom, url, type_source="rss", langue="fr",
                  frequence_heures=168, cree_par=None):
    sid = new_id()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO sources
                (id, nom, url, type_source, langue, active,
                 frequence_heures, cree_le, cree_par)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
        """, (sid, nom, url, type_source, langue,
              frequence_heures, now_iso(), cree_par))
    return sid

def toggle_source(sid, active):
    with get_db() as conn:
        conn.execute(
            "UPDATE sources SET active = ? WHERE id = ?",
            (1 if active else 0, sid)
        )

def delete_source(sid):
    with get_db() as conn:
        conn.execute("DELETE FROM sources WHERE id = ?", (sid,))

def get_notifications(utilisateur_id, non_lues_only=False):
    with get_db() as conn:
        q = "SELECT * FROM notifications WHERE utilisateur_id = ?"
        params = [utilisateur_id]
        if non_lues_only:
            q += " AND lue = 0"
        q += " ORDER BY cree_le DESC LIMIT 50"
        return [dict(r) for r in conn.execute(q, params).fetchall()]

def mark_notification_lue(notif_id):
    with get_db() as conn:
        conn.execute(
            "UPDATE notifications SET lue = 1 WHERE id = ?", (notif_id,)
        )

def create_notification(utilisateur_id, message, dimension=None):
    with get_db() as conn:
        conn.execute("""
            INSERT INTO notifications
                (id, utilisateur_id, message, dimension, lue, cree_le)
            VALUES (?, ?, ?, ?, 0, ?)
        """, (new_id(), utilisateur_id, message, dimension, now_iso()))

def count_non_lues(utilisateur_id):
    with get_db() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM notifications "
            "WHERE utilisateur_id=? AND lue=0",
            (utilisateur_id,)
        ).fetchone()
        return row[0] if row else 0


def get_actions_diif(dimension: str = None,
                     limit: int = 20) -> list:
    """Retourne les actions DIIF enregistrées."""
    try:
        with get_db() as conn:
            if dimension:
                rows = conn.execute("""
                    SELECT * FROM historique_actions_diif
                    WHERE dimension = ? OR dimension IS NULL
                    ORDER BY date_action DESC LIMIT ?
                """, (dimension, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM historique_actions_diif
                    ORDER BY date_action DESC LIMIT ?
                """, (limit,)).fetchall()
            return [dict(r) for r in rows]
    except Exception:
        return []


def sauvegarder_action_diif(action: dict) -> bool:
    """Enregistre une action DIIF."""
    try:
        with get_db() as conn:
            conn.execute("""
                INSERT INTO historique_actions_diif
                    (id, titre, description, dimension, zone,
                     date_action, statut, source_info,
                     cree_par, cree_le)
                VALUES
                    (:id, :titre, :description, :dimension, :zone,
                     :date_action, :statut, :source_info,
                     :cree_par, :cree_le)
            """, action)
        return True
    except Exception:
        return False


def get_stats_dashboard() -> dict:
    """Statistiques pour le tableau de bord."""
    with get_db() as conn:
        total_articles = conn.execute(
            "SELECT COUNT(*) FROM articles"
        ).fetchone()[0]
        total_docs = conn.execute(
            "SELECT COUNT(*) FROM documents"
        ).fetchone()[0]
        sources_actives = conn.execute(
            "SELECT COUNT(*) FROM sources WHERE active = 1"
        ).fetchone()[0]
        derniere_collecte = conn.execute(
            "SELECT MAX(collecte_le) FROM articles"
        ).fetchone()[0]
        par_source = conn.execute("""
            SELECT s.nom, COUNT(*) as nb,
                   s.langue,
                   MAX(a.collecte_le) as derniere
            FROM articles a
            JOIN sources s ON a.source_id = s.id
            GROUP BY s.nom ORDER BY nb DESC
        """).fetchall()
        par_langue = conn.execute("""
            SELECT langue, COUNT(*) as nb
            FROM articles GROUP BY langue
        """).fetchall()
        par_mois = conn.execute("""
            SELECT SUBSTR(collecte_le, 1, 7) as mois,
                   COUNT(*) as nb
            FROM articles
            WHERE collecte_le IS NOT NULL
            GROUP BY mois
            ORDER BY mois DESC
            LIMIT 12
        """).fetchall()
        par_dimension = conn.execute("""
            SELECT qualite_contenu, COUNT(*) as nb
            FROM articles GROUP BY qualite_contenu
        """).fetchall()
    return {
        "total_articles":    total_articles,
        "total_docs":        total_docs,
        "sources_actives":   sources_actives,
        "derniere_collecte": derniere_collecte,
        "par_source":        [dict(r) for r in par_source],
        "par_langue":        [dict(r) for r in par_langue],
        "par_mois":          [dict(r) for r in par_mois],
        "par_dimension":     [dict(r) for r in par_dimension],
    }


# ──────────────────────────────────────────────────────────────────────────────
# Interactions chatbot — traçabilité des échanges RAG (évaluation)
# ──────────────────────────────────────────────────────────────────────────────

def enregistrer_interaction(utilisateur_id,
                            requete_utilisateur,
                            requete_rag_utilisee,
                            dimension_detectee,
                            chunks_recuperes,
                            reponse_generee,
                            sources_citees,
                            interaction_id=None):
    """
    Enregistre une interaction chatbot dans interactions_chatbot.

    chunks_recuperes : liste de dicts {chunk_id, article_id, score, source}
    sources_citees   : liste de dicts (source, titre, url, date, score)

    Retourne l'id de l'interaction (généré si non fourni).
    """
    iid = interaction_id or new_id()
    with get_db() as conn:
        conn.execute("""
            INSERT INTO interactions_chatbot
                (id, utilisateur_id, requete_utilisateur, requete_rag_utilisee,
                 dimension_detectee, chunks_recuperes, reponse_generee,
                 sources_citees, horodatage)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            iid,
            utilisateur_id,
            requete_utilisateur,
            requete_rag_utilisee,
            dimension_detectee,
            json.dumps(chunks_recuperes or [], ensure_ascii=False),
            reponse_generee,
            json.dumps(sources_citees or [], ensure_ascii=False),
            now_iso(),
        ))
    return iid


def get_interactions(limit=200, utilisateur_id=None):
    """Retourne les dernières interactions chatbot (JSON désérialisé)."""
    with get_db() as conn:
        if utilisateur_id:
            rows = conn.execute("""
                SELECT i.*, u.nom, u.email FROM interactions_chatbot i
                LEFT JOIN utilisateurs u ON i.utilisateur_id = u.id
                WHERE i.utilisateur_id = ?
                ORDER BY i.horodatage DESC LIMIT ?
            """, (utilisateur_id, limit)).fetchall()
        else:
            rows = conn.execute("""
                SELECT i.*, u.nom, u.email FROM interactions_chatbot i
                LEFT JOIN utilisateurs u ON i.utilisateur_id = u.id
                ORDER BY i.horodatage DESC LIMIT ?
            """, (limit,)).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        for champ in ("chunks_recuperes", "sources_citees"):
            try:
                d[champ] = json.loads(d.get(champ) or "[]")
            except Exception:
                d[champ] = []
        out.append(d)
    return out


def get_stats_interactions() -> dict:
    """
    Statistiques agrégées sur interactions_chatbot pour la page d'évaluation :
    volume total, distribution par dimension, distribution des scores de chunks.
    """
    stats = {
        "total":            0,
        "par_dimension":    [],
        "par_jour":         [],
        "scores_chunks":    [],
        "avec_feedback":    0,
        "feedback_positif": 0,
        "feedback_negatif": 0,
    }
    with get_db() as conn:
        stats["total"] = conn.execute(
            "SELECT COUNT(*) FROM interactions_chatbot"
        ).fetchone()[0]

        if stats["total"] == 0:
            return stats

        par_dim = conn.execute("""
            SELECT COALESCE(dimension_detectee, 'Non détectée') AS dimension,
                   COUNT(*) AS nb
            FROM interactions_chatbot
            GROUP BY dimension_detectee
            ORDER BY nb DESC
        """).fetchall()
        stats["par_dimension"] = [dict(r) for r in par_dim]

        par_jour = conn.execute("""
            SELECT SUBSTR(horodatage, 1, 10) AS jour, COUNT(*) AS nb
            FROM interactions_chatbot
            GROUP BY jour ORDER BY jour DESC LIMIT 30
        """).fetchall()
        stats["par_jour"] = [dict(r) for r in par_jour]

        # Distribution des scores de chunks (parsés depuis le JSON)
        rows = conn.execute(
            "SELECT chunks_recuperes FROM interactions_chatbot"
        ).fetchall()
        scores = []
        for r in rows:
            try:
                for c in json.loads(r[0] or "[]"):
                    s = c.get("score")
                    if isinstance(s, (int, float)):
                        scores.append(float(s))
            except Exception:
                continue
        stats["scores_chunks"] = scores

        # Feedback agrégé (table optionnelle)
        try:
            fb = conn.execute("""
                SELECT note, COUNT(*) AS nb
                FROM feedback_reponses GROUP BY note
            """).fetchall()
            for r in fb:
                if r["note"] == 1:
                    stats["feedback_positif"] = r["nb"]
                elif r["note"] == -1:
                    stats["feedback_negatif"] = r["nb"]
            stats["avec_feedback"] = (
                stats["feedback_positif"] + stats["feedback_negatif"]
            )
        except Exception:
            pass

    return stats


# ──────────────────────────────────────────────────────────────────────────────
# Feedback utilisateur sur les réponses du chatbot
# ──────────────────────────────────────────────────────────────────────────────

def enregistrer_feedback(interaction_id, note, utilisateur_id=None,
                         commentaire=None):
    """
    Enregistre un feedback (note = 1 ou -1) sur une réponse du chatbot.
    Retourne l'id du feedback ou None en cas d'échec.
    """
    try:
        fid = new_id()
        with get_db() as conn:
            conn.execute("""
                INSERT INTO feedback_reponses
                    (id, interaction_id, note, commentaire,
                     utilisateur_id, horodatage)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (fid, interaction_id, note, commentaire,
                  utilisateur_id, now_iso()))
        return fid
    except Exception:
        return None
