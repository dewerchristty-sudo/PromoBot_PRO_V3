from datetime import datetime, timedelta, timezone
import unittest

from src.offers import (
    OfferAnalysisPolicy,
    OfferCandidate,
    OfferIdentity,
    OfferRanking,
    RankedOffer,
    ScoreResult,
)


class OfferRankingTest(unittest.TestCase):

    def setUp(self):
        self.now = datetime(2026, 7, 26, 12, tzinfo=timezone.utc)
        self.identity_service = OfferIdentity()
        self.ranking = OfferRanking(OfferAnalysisPolicy(
            ranking_max_per_category=1,
            ranking_max_per_store=2,
            ranking_max_per_identity=1,
        ))

    def offer(
        self,
        title,
        score,
        confidence=5,
        current=80,
        previous=100,
        category="Tecnologia",
        store="Amazon",
        minutes=0,
    ):
        candidate = OfferCandidate(
            title=title,
            store=store,
            category=category,
            current_price=current,
            previous_price=previous,
            collected_at=self.now - timedelta(minutes=minutes),
        )
        identity = self.identity_service.identify(candidate)
        return RankedOffer(
            candidate=candidate,
            score=ScoreResult(
                total=score,
                classification=(
                    "oferta_excelente" if score >= 90
                    else "boa_oferta" if score >= 70
                    else "oferta_media" if score >= 50
                    else "oferta_fraca"
                ),
                components={},
                policy_version=1,
                confidence=confidence,
            ),
            identity=identity,
        )

    def test_maior_score_fica_primeiro(self):
        ranked = self.ranking.rank([
            self.offer("Produto A", 70),
            self.offer("Produto B", 90, category="Casa"),
        ], diversity=False)
        self.assertEqual(ranked[0].score.total, 90)

    def test_empate_resolvido_por_confianca(self):
        ranked = self.ranking.rank([
            self.offer("Produto A", 80, confidence=4),
            self.offer("Produto B", 80, confidence=7),
        ], diversity=False)
        self.assertEqual(ranked[0].score.confidence, 7)

    def test_empate_resolvido_pela_economia(self):
        ranked = self.ranking.rank([
            self.offer("Produto A", 80, current=90, previous=100),
            self.offer("Produto B", 80, current=60, previous=100),
        ], diversity=False)
        self.assertEqual(ranked[0].candidate.title, "Produto B")

    def test_ranking_e_deterministico(self):
        offers = [
            self.offer("Produto B", 80),
            self.offer("Produto A", 80),
        ]
        first = [item.identity.signature for item in self.ranking.rank(
            offers,
            diversity=False,
        )]
        second = [item.identity.signature for item in self.ranking.rank(
            list(reversed(offers)),
            diversity=False,
        )]
        self.assertEqual(first, second)

    def test_duplicados_nao_ocupam_varias_posicoes(self):
        ranked = self.ranking.rank([
            self.offer("SSD Kingston NV3 1TB", 90),
            self.offer("Kingston NV3 SSD 1000GB", 85),
        ], diversity=False)
        self.assertEqual(len(ranked), 1)

    def test_diversidade_por_categoria_e_loja(self):
        offers = [
            self.offer("Notebook A", 95, category="Tecnologia", store="Amazon"),
            self.offer("Notebook B", 94, category="Tecnologia", store="Amazon"),
            self.offer("Geladeira A", 93, category="Casa", store="Amazon"),
            self.offer("Perfume A", 92, category="Beleza", store="Shopee"),
        ]
        ranked = self.ranking.rank(offers, limit=3)
        self.assertEqual(
            {item.candidate.category for item in ranked},
            {"Tecnologia", "Casa", "Beleza"},
        )
        self.assertLessEqual(
            sum(item.candidate.store == "Amazon" for item in ranked),
            2,
        )

    def test_selecao_top3_top5_e_poucas_ofertas(self):
        offers = [
            self.offer(
                f"Produto {index}",
                100 - index,
                category=f"Categoria {index}",
                store=("Mercado Livre", "Amazon", "Shopee")[index % 3],
            )
            for index in range(7)
        ]
        self.assertEqual(len(self.ranking.top3(offers)), 3)
        self.assertEqual(len(self.ranking.top5(offers)), 5)
        self.assertEqual(len(self.ranking.rank(offers[:2], 10)), 2)


if __name__ == "__main__":
    unittest.main()
