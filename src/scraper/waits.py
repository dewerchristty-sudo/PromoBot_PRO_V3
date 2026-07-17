class Waits:

    @staticmethod
    def page(page, milliseconds=3000):

        page.wait_for_timeout(milliseconds)

    # ==========================================

    @staticmethod
    def network(page):

        page.wait_for_load_state(
            "networkidle"
        )

    # ==========================================

    @staticmethod
    def dom(page):

        page.wait_for_load_state(
            "domcontentloaded"
        )

    # ==========================================

    @staticmethod
    def full(page):

        Waits.dom(page)

        Waits.network(page)

        Waits.page(page, 2000)