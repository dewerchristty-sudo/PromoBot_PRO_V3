import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from src.ui.shopee_variation_dialog import ShopeeVariationDialog


class ShopeeVariationDialogLogicTest(unittest.TestCase):

    def product(self, price="25,98"):
        return {
            "preco": price,
            "origem_preco": "cupom",
            "variacao_model_id": "103",
            "variacao_selecionada": "Rosa / G",
            "estoque_variacao": 7,
        }

    def test_confirmacao_rele_preco_estoque_e_selecao(self):
        current = self.product()
        dialog = SimpleNamespace(
            preview_product=current,
            preview_callback=Mock(return_value=dict(current)),
            complete_selection=Mock(
                return_value={"Cor": "Rosa", "Tamanho": "G"}
            ),
            preview_label=Mock(),
            invalidate_preview=Mock(),
            destroy=Mock(),
            result=("cancel", None),
        )
        ShopeeVariationDialog.confirm(dialog)
        dialog.preview_callback.assert_called_once_with(
            {"Cor": "Rosa", "Tamanho": "G"}
        )
        self.assertEqual(dialog.result, ("confirm", current))
        dialog.destroy.assert_called_once()

    def test_mudanca_de_preco_impede_confirmacao_imediata(self):
        original = self.product("25,98")
        changed = self.product("27,98")
        dialog = SimpleNamespace(
            preview_product=original,
            preview_callback=Mock(return_value=changed),
            complete_selection=Mock(return_value={"Cor": "Rosa"}),
            preview_label=Mock(),
            invalidate_preview=Mock(),
            destroy=Mock(),
            result=("cancel", None),
        )
        ShopeeVariationDialog.confirm(dialog)
        self.assertEqual(dialog.preview_product, changed)
        self.assertEqual(dialog.result, ("cancel", None))
        dialog.destroy.assert_not_called()
        dialog.preview_label.configure.assert_called_once()

    def test_alterar_opcao_invalida_preco_anterior(self):
        dialog = SimpleNamespace(
            invalidate_preview=Mock(),
            refresh_menus=Mock(),
        )
        ShopeeVariationDialog.option_changed(dialog, 1)
        dialog.invalidate_preview.assert_called_once()
        dialog.refresh_menus.assert_called_once_with(2)

    def test_cancelar_nao_retorna_produto(self):
        dialog = SimpleNamespace(result=("confirm", self.product()), destroy=Mock())
        ShopeeVariationDialog.cancel(dialog)
        self.assertEqual(dialog.result, ("cancel", None))
        dialog.destroy.assert_called_once()

    def test_preenchimento_manual_nao_retorna_preco_automatico(self):
        dialog = SimpleNamespace(result=("confirm", self.product()), destroy=Mock())
        ShopeeVariationDialog.manual(dialog)
        self.assertEqual(dialog.result, ("manual", None))
        dialog.destroy.assert_called_once()


if __name__ == "__main__":
    unittest.main()
