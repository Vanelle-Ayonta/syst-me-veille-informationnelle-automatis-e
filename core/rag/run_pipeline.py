"""
core/rag/run_pipeline.py — Script CLI
Usage :
    python core/rag/run_pipeline.py              # pipeline incrémental
    python core/rag/run_pipeline.py --stats      # statistiques
    python core/rag/run_pipeline.py --rebuild    # reconstruction complète
    python core/rag/run_pipeline.py --test "mobile money CEMAC"
    python core/rag/run_pipeline.py --decharger  # libérer la RAM
"""
import sys, os, argparse, logging
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__)))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="Pipeline RAG — Système de veille DIIF/BEAC"
    )
    ap.add_argument("--stats",     action="store_true",
                    help="Afficher les statistiques")
    ap.add_argument("--rebuild",   action="store_true",
                    help="Reconstruire l'index depuis zéro")
    ap.add_argument("--decharger", action="store_true",
                    help="Décharger l'index de la RAM")
    ap.add_argument("--test",      metavar="REQUETE",
                    help="Tester la recherche sémantique")
    args = ap.parse_args()

    if args.stats:
        from core.rag.pipeline import get_stats
        s = get_stats()
        c = s["chunks"]
        i = s["index"]
        print(f"\n{'─'*45}")
        print(f"  PIPELINE RAG — ÉTAT")
        print(f"{'─'*45}")
        print(f"  Articles avec contenu  : {c['articles_total']}")
        print(f"  Articles chunkés       : {c['articles_chunkés']}")
        print(f"  Articles restants      : {c['articles_restants']}")
        print(f"  Chunks total           : {c['total']}")
        print(f"  Chunks indexés         : {c['indexes']}")
        print(f"  Chunks en attente      : {c['en_attente']}")
        print(f"  Vecteurs FAISS         : {i['total_vecteurs']}")
        print(f"  Taille index           : {i['taille_mo']} Mo")
        print(f"  Index en mémoire       : {i.get('en_memoire', False)}")
        print(f"{'─'*45}\n")

    elif args.rebuild:
        from core.rag.indexer import reconstruire_index_complet
        print("Reconstruction de l'index FAISS depuis zéro...")
        stats = reconstruire_index_complet()
        print(f"Terminé — {stats['total_index']} vecteurs.")

    elif args.decharger:
        from core.rag.indexer import decharger_index
        decharger_index()
        print("Index déchargé de la RAM.")

    elif args.test:
        from core.rag.pipeline import search
        print(f"\nRequête : \"{args.test}\"")
        print("─" * 50)
        resultats = search(args.test, top_k=5)
        if not resultats:
            print("Aucun résultat — vérifiez que l'index est rempli.")
        else:
            print(f"{len(resultats)} résultat(s)\n")
            for i, r in enumerate(resultats):
                print(f"[{i+1}] Score  : {r['score']:.3f}")
                print(f"     Source : {r['source_nom']}")
                print(f"     Titre  : {(r['titre'] or '')[:70]}")
                print(f"     Extrait: {r['contenu'][:200]}...")
                print()

    else:
        from core.rag.pipeline import run_pipeline
        print("\nPipeline RAG — Mode incrémental")
        print("(seuls les nouveaux articles et chunks sont traités)")
        print("=" * 50)
        stats = run_pipeline()
        print(f"\nRésumé :")
        print(f"  Articles chunkés  : {stats.get('articles', 0)}")
        print(f"  Chunks créés      : {stats.get('chunks', 0)}")
        print(f"  Chunks indexés    : {stats.get('indexés', 0)}")
        print(f"  Total index FAISS : {stats.get('total_index', 0)}")
