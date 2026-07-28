from tkinter import messagebox

import customtkinter as ctk

from src.stores.shopee import Shopee


class ShopeeVariationDialog(ctk.CTkToplevel):
    PLACEHOLDER = "Selecione..."

    def __init__(self, master, catalog, preview_callback):
        super().__init__(master)
        self.catalog = catalog
        self.preview_callback = preview_callback
        self.result = ("cancel", None)
        self.preview_product = None
        self.variables = []
        self.menus = []

        self.title("Selecionar variação da Shopee")
        self.geometry("610x560")
        self.minsize(560, 500)
        self.transient(master.winfo_toplevel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            self,
            text="Selecionar variação",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).grid(row=0, column=0, padx=24, pady=(22, 8), sticky="w")
        ctk.CTkLabel(
            self,
            text=(
                "Escolha todas as opções. Nenhum preço será usado antes "
                "da sua confirmação."
            ),
            anchor="w",
            justify="left",
        ).grid(row=1, column=0, padx=24, pady=(0, 16), sticky="ew")

        options_frame = ctk.CTkScrollableFrame(self)
        options_frame.grid(row=2, column=0, padx=24, sticky="nsew")
        options_frame.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)

        for index, group in enumerate(catalog.get("groups") or []):
            ctk.CTkLabel(
                options_frame,
                text=group["name"],
                anchor="w",
            ).grid(row=index * 2, column=0, pady=(8, 3), sticky="ew")
            variable = ctk.StringVar(value=self.PLACEHOLDER)
            menu = ctk.CTkOptionMenu(
                options_frame,
                variable=variable,
                values=[self.PLACEHOLDER],
                command=lambda _value, position=index: self.option_changed(
                    position
                ),
            )
            menu.grid(row=index * 2 + 1, column=0, sticky="ew")
            menu.set(self.PLACEHOLDER)
            self.variables.append(variable)
            self.menus.append(menu)

        self.preview_label = ctk.CTkLabel(
            self,
            text="Selecione todas as opções para consultar o preço.",
            anchor="w",
            justify="left",
        )
        self.preview_label.grid(
            row=3,
            column=0,
            padx=24,
            pady=16,
            sticky="ew",
        )

        button_frame = ctk.CTkFrame(self, fg_color="transparent")
        button_frame.grid(row=4, column=0, padx=24, pady=(0, 22), sticky="ew")
        for column in range(4):
            button_frame.grid_columnconfigure(column, weight=1)

        self.consult_button = ctk.CTkButton(
            button_frame,
            text="Consultar preço",
            command=self.consult,
        )
        self.consult_button.grid(row=0, column=0, padx=(0, 5), sticky="ew")
        self.confirm_button = ctk.CTkButton(
            button_frame,
            text="Confirmar",
            state="disabled",
            fg_color="#17813f",
            command=self.confirm,
        )
        self.confirm_button.grid(row=0, column=1, padx=5, sticky="ew")
        ctk.CTkButton(
            button_frame,
            text="Preencher manualmente",
            command=self.manual,
        ).grid(row=0, column=2, padx=5, sticky="ew")
        ctk.CTkButton(
            button_frame,
            text="Cancelar",
            fg_color="#b52d2d",
            command=self.cancel,
        ).grid(row=0, column=3, padx=(5, 0), sticky="ew")

        self.refresh_menus(0)
        self.grab_set()
        self.focus_force()

    def selection_before(self, group_index):
        return {
            self.catalog["groups"][index]["name"]: self.variables[index].get()
            for index in range(group_index)
            if self.variables[index].get() != self.PLACEHOLDER
        }

    def complete_selection(self):
        selection = {}
        for group, variable in zip(self.catalog["groups"], self.variables):
            value = variable.get()
            if value == self.PLACEHOLDER:
                return {}
            selection[group["name"]] = value
        return selection

    def refresh_menus(self, start_index):
        for index in range(start_index, len(self.menus)):
            prior = self.selection_before(index)
            previous_complete = len(prior) == index
            values = (
                Shopee.available_variation_options(
                    self.catalog,
                    index,
                    prior,
                )
                if previous_complete
                else []
            )
            self.menus[index].configure(
                values=[self.PLACEHOLDER, *values],
                state="normal" if values else "disabled",
            )
            self.variables[index].set(self.PLACEHOLDER)
            self.menus[index].set(self.PLACEHOLDER)

    def invalidate_preview(self):
        self.preview_product = None
        self.confirm_button.configure(state="disabled")
        self.preview_label.configure(
            text="Selecione todas as opções para consultar o preço."
        )

    def option_changed(self, index):
        self.invalidate_preview()
        self.refresh_menus(index + 1)

    def consult(self):
        selection = self.complete_selection()
        if not selection:
            messagebox.showwarning(
                "Seleção incompleta",
                "Selecione todas as opções obrigatórias.",
                parent=self,
            )
            return
        self.consult_button.configure(state="disabled", text="Consultando...")
        self.update_idletasks()
        try:
            product = self.preview_callback(selection)
        except (ValueError, RuntimeError) as error:
            messagebox.showerror(
                "Variação indisponível",
                str(error),
                parent=self,
            )
            self.invalidate_preview()
            return
        finally:
            self.consult_button.configure(
                state="normal",
                text="Consultar preço",
            )

        self.preview_product = product
        self.preview_label.configure(
            text=(
                f"Variação: {product.get('variacao_selecionada', '')}\n"
                f"Preço: R$ {product.get('preco', '')}\n"
                f"Origem: {product.get('origem_preco', '')}\n"
                f"Estoque: {product.get('estoque_variacao', 0)}"
            )
        )
        self.confirm_button.configure(state="normal")

    def confirm(self):
        if not self.preview_product:
            return
        # Relê seleção, estoque e preço imediatamente antes de salvar.
        try:
            product = self.preview_callback(self.complete_selection())
        except (ValueError, RuntimeError) as error:
            messagebox.showerror(
                "Variação alterada",
                str(error),
                parent=self,
            )
            self.invalidate_preview()
            return
        if (
            product.get("preco") != self.preview_product.get("preco")
            or product.get("origem_preco")
            != self.preview_product.get("origem_preco")
            or product.get("variacao_model_id")
            != self.preview_product.get("variacao_model_id")
        ):
            self.preview_product = product
            self.preview_label.configure(
                text=(
                    "O preço ou a disponibilidade mudou. Confira novamente:\n"
                    f"Variação: {product.get('variacao_selecionada', '')}\n"
                    f"Preço: R$ {product.get('preco', '')}\n"
                    f"Origem: {product.get('origem_preco', '')}\n"
                    f"Estoque: {product.get('estoque_variacao', 0)}"
                )
            )
            return
        self.result = ("confirm", product)
        self.destroy()

    def manual(self):
        self.result = ("manual", None)
        self.destroy()

    def cancel(self):
        self.result = ("cancel", None)
        self.destroy()


def request_shopee_variation(master, catalog, preview_callback):
    dialog = ShopeeVariationDialog(master, catalog, preview_callback)
    master.wait_window(dialog)
    return dialog.result
