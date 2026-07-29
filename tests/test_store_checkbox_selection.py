import inspect
import unittest

from src.ui.category_hub_page import CategoryHubPage
from src.ui.monitor_page import MonitorPage
from src.ui.search_page import SearchPage


class StoreCheckboxSelectionTest(unittest.TestCase):

    def test_search_store_checkboxes_are_not_disabled(self):
        source = inspect.getsource(SearchPage.criar_interface)

        self.assertIn("CTkCheckBox", source)
        self.assertNotIn('"disabled"', source)

    def test_monitor_store_checkboxes_are_not_disabled(self):
        source = inspect.getsource(MonitorPage.criar_interface)

        self.assertIn("CTkCheckBox", source)
        self.assertNotIn('"disabled"', source)

    def test_category_hub_reuses_search_page_with_toggleable_checkboxes(self):
        source = inspect.getsource(CategoryHubPage.create_interface)

        self.assertIn("self.search_page = SearchPage(", source)
        self.assertNotIn(
            '"disabled"',
            inspect.getsource(SearchPage.criar_interface),
        )


if __name__ == "__main__":
    unittest.main()
