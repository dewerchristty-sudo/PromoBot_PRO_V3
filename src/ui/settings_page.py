import threading
import tkinter as tk
from tkinter import messagebox

import customtkinter as ctk

from src.core.notifier import Notifier
from src.core.startup import configure_startup, startup_enabled
from src.core.store_manager import StoreManager
from src.core.whatsapp_control import WhatsAppControl


class SettingsPage(ctk.CTkFrame):

    def __init__(self, master, database):
        super().__init__(master)
        self.database = database
        self.notifier = Notifier(database)
        self.whatsapp_control = WhatsAppControl()
        self.start_with_windows = tk.BooleanVar(value=startup_enabled())
        self.qr_window = None
        self.qr_ctk_image = None
        self.catalog_analysis = None
        self.catalog_buttons = []
        self.criar_interface()

    def criar_interface(self):
        ctk.CTkLabel(self, text="Configurações", font=("Arial", 30, "bold")).pack(pady=(20, 15))

        painel = ctk.CTkFrame(self)
        painel.pack(fill="x", padx=20, pady=10)
        self.aparencia = ctk.CTkOptionMenu(painel, values=["Dark", "Light", "System"], command=self.alterar_tema)
        self.aparencia.set("Dark")
        ctk.CTkLabel(painel, text="Tema da interface", font=("Arial", 16, "bold")).grid(row=0, column=0, sticky="w", padx=16, pady=(16, 6))
        self.aparencia.grid(row=1, column=0, sticky="w", padx=16, pady=(0, 16))
        ctk.CTkSwitch(
            painel,
            text="Iniciar o PromoBot automaticamente com o Windows",
            variable=self.start_with_windows,
            command=self.toggle_startup,
        ).grid(row=2, column=0, sticky="w", padx=16, pady=(0, 16))

        conexao = ctk.CTkFrame(self)
        conexao.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(conexao, text="WhatsApp local (Docker + Evolution API)", font=("Arial", 16, "bold")).pack(anchor="w", padx=16, pady=(14, 8))
        botoes = ctk.CTkFrame(conexao, fg_color="transparent")
        botoes.pack(fill="x", padx=10)
        self.integration_buttons = []
        for text, command in (
            ("Abrir Docker Desktop", self.open_docker),
            ("Iniciar Evolution API", self.start_evolution),
            ("Conectar WhatsApp", self.connect_whatsapp),
            ("Verificar conexão", self.check_connection),
            ("Parar serviços", self.stop_evolution),
        ):
            button = ctk.CTkButton(botoes, text=text, command=command)
            button.pack(side="left", padx=6, pady=6)
            self.integration_buttons.append(button)
        self.connection_status = ctk.CTkLabel(conexao, text="Status: aguardando verificação", anchor="w")
        self.connection_status.pack(fill="x", padx=16, pady=(4, 14))

        catalog = ctk.CTkFrame(self)
        catalog.pack(fill="x", padx=20, pady=10)
        ctk.CTkLabel(
            catalog,
            text="Limpeza inteligente do catálogo",
            font=("Arial", 16, "bold"),
        ).pack(anchor="w", padx=16, pady=(14, 4))
        ctk.CTkLabel(
            catalog,
            text=(
                "Preserva produtos recentes, promoções, links afiliados, envios e "
                "pendências prioritárias."
            ),
        ).pack(anchor="w", padx=16, pady=(0, 8))
        catalog_actions = ctk.CTkFrame(catalog, fg_color="transparent")
        catalog_actions.pack(fill="x", padx=10)
        analyze_button = ctk.CTkButton(
            catalog_actions, text="Analisar catálogo", command=self.analyze_catalog
        )
        analyze_button.pack(side="left", padx=6, pady=6)
        clean_button = ctk.CTkButton(
            catalog_actions,
            text="Fazer backup e limpar",
            fg_color="#b56a12",
            hover_color="#8f510b",
            command=self.clean_catalog,
        )
        clean_button.pack(side="left", padx=6, pady=6)
        self.catalog_buttons.extend([analyze_button, clean_button])
        self.catalog_status = ctk.CTkLabel(
            catalog,
            text="Clique em Analisar catálogo. Nenhum dado será apagado nessa etapa.",
            anchor="w",
            justify="left",
        )
        self.catalog_status.pack(fill="x", padx=16, pady=(4, 14))

        info = ctk.CTkTextbox(self, height=180)
        info.pack(fill="x", padx=20, pady=20)
        canais = self.notifier.configured_channels()
        canais_texto = ", ".join(canais) if canais else "nenhum canal configurado"
        grupos = self.notifier.whatsapp_category_groups()
        integridade = self.database.verificar_integridade()
        lojas_principais = "\n".join(f"- {loja}" for loja in StoreManager.stable_store_names())
        info.insert(
            "end",
            "Diagnóstico local:\n"
            f"- Banco: {integridade}\n"
            f"- Produtos: {self.database.total_produtos()}\n"
            f"- Links afiliados: {self.database.total_links_afiliados()}\n"
            f"- Fila de recuperação: {self.database.total_fila_notificacoes()}\n"
            f"- Pendências para revisão: {self.database.total_pendencias_revisao()}\n"
            f"- Grupos por categoria: {len(grupos)}/6\n\n"
            "Lojas principais:\n"
            f"{lojas_principais}\n\n"
            "Notificações:\n"
            f"- {canais_texto}\n"
            "- Envios automáticos respeitam o horário definido no .env\n"
            "- Configure .env usando .env.example como modelo\n"
        )
        info.configure(state="disabled")

    def alterar_tema(self, tema):
        ctk.set_appearance_mode(tema.lower())

    def _set_catalog_buttons(self, enabled):
        state = "normal" if enabled else "disabled"
        for button in self.catalog_buttons:
            button.configure(state=state)

    @staticmethod
    def _catalog_report(data):
        return (
            f"Banco atual: {data['banco_mb']} MB | Produtos: {data['total_produtos']}\n"
            f"Produtos removíveis: {data['produtos_removiveis']} "
            f"({data['produtos_antigos']} antigos; "
            f"{data['produtos_incompletos']} incompletos)\n"
            f"Preços históricos removíveis: {data['historicos_removiveis']} | "
            f"Ignorados antigos: {data['ignorados_antigos']} | "
            f"Eventos antigos: {data['eventos_antigos']}"
        )

    def analyze_catalog(self):
        self._set_catalog_buttons(False)
        self.catalog_status.configure(text="Analisando catálogo, aguarde...")

        def worker():
            try:
                result = self.database.analisar_limpeza_catalogo(90, 10)
                self.after(0, lambda: self._catalog_analyzed(result))
            except Exception as error:
                message = str(error)
                self.after(0, lambda: self._catalog_error(message))

        threading.Thread(target=worker, daemon=True).start()

    def _catalog_analyzed(self, result):
        self.catalog_analysis = result
        self._set_catalog_buttons(True)
        self.catalog_status.configure(text=self._catalog_report(result))

    def clean_catalog(self):
        if not self.catalog_analysis:
            messagebox.showinfo(
                "Limpeza inteligente",
                "Clique primeiro em Analisar catálogo para conferir o que será removido.",
            )
            return
        analysis = self.catalog_analysis
        if not messagebox.askyesno(
            "Confirmar limpeza inteligente",
            self._catalog_report(analysis)
            + "\n\nUm backup completo será criado antes da exclusão. Continuar?",
        ):
            return
        self._set_catalog_buttons(False)
        self.catalog_status.configure(text="Criando backup e limpando, aguarde...")

        def worker():
            try:
                result = self.database.limpar_catalogo_inteligente(90, 10)
                self.after(0, lambda: self._catalog_cleaned(result))
            except Exception as error:
                message = str(error)
                self.after(0, lambda: self._catalog_error(message))

        threading.Thread(target=worker, daemon=True).start()

    def _catalog_cleaned(self, result):
        self.catalog_analysis = None
        self._set_catalog_buttons(True)
        message = (
            f"Produtos removidos: {result['produtos_removidos']}\n"
            f"Preços históricos removidos: {result['historicos_removidos']}\n"
            f"Ignorados antigos: {result['ignorados_removidos']}\n"
            f"Eventos antigos: {result['eventos_removidos']}\n\n"
            f"Backup: {result['backup']}"
        )
        self.catalog_status.configure(text="Limpeza concluída. Analise novamente para atualizar.")
        messagebox.showinfo("Limpeza inteligente concluída", message)

    def _catalog_error(self, message):
        self._set_catalog_buttons(True)
        self.catalog_status.configure(text=f"Falha na limpeza: {message}")
        messagebox.showerror("Limpeza inteligente", message)

    def toggle_startup(self):
        try:
            enabled = configure_startup(self.start_with_windows.get())
            self.start_with_windows.set(enabled)
        except Exception as error:
            self.start_with_windows.set(startup_enabled())
            messagebox.showerror("Inicialização automática", str(error))

    def _run_async(self, action, success=None):
        for button in self.integration_buttons:
            button.configure(state="disabled")
        self.connection_status.configure(text="Status: processando...")

        def worker():
            try:
                result = action()
                self.after(0, lambda: success(result) if success else self._show_result(result))
            except Exception as error:
                message = str(error)
                self.after(0, lambda: self._show_error(message))

        threading.Thread(target=worker, daemon=True).start()

    def _enable_buttons(self):
        for button in self.integration_buttons:
            button.configure(state="normal")

    def _show_result(self, message):
        self._enable_buttons()
        self.connection_status.configure(text=f"Status: {message}")

    def _show_error(self, message):
        self._enable_buttons()
        self.connection_status.configure(text=f"Status: erro — {message}")
        messagebox.showerror("Integração WhatsApp", message)

    def open_docker(self):
        self._run_async(self.whatsapp_control.open_docker_desktop)

    def start_evolution(self):
        self._run_async(self.whatsapp_control.start_evolution)

    def stop_evolution(self):
        self._run_async(self.whatsapp_control.stop_evolution)

    def check_connection(self):
        self._run_async(self.whatsapp_control.connection_state, self._connection_checked)

    def _connection_checked(self, state):
        labels = {
            "open": "WhatsApp conectado",
            "connected": "WhatsApp conectado",
            "online": "WhatsApp conectado",
            "close": "WhatsApp desconectado",
            "not_created": "instância ainda não criada",
        }
        self._show_result(labels.get(state, f"WhatsApp: {state}"))

    def connect_whatsapp(self):
        self._run_async(self.whatsapp_control.connect_whatsapp, self._connection_ready)

    def _connection_ready(self, result):
        kind, image = result
        self._enable_buttons()
        if kind == "connected":
            self.connection_status.configure(text="Status: WhatsApp conectado")
            messagebox.showinfo("WhatsApp", "O WhatsApp já está conectado.")
            return
        self.connection_status.configure(text="Status: leia o QR Code no WhatsApp")
        self._show_qr(image)

    def _show_qr(self, image):
        if self.qr_window is not None and self.qr_window.winfo_exists():
            self.qr_window.destroy()
        self.qr_window = ctk.CTkToplevel(self)
        self.qr_window.title("Conectar WhatsApp")
        self.qr_window.geometry("430x500")
        self.qr_window.transient(self.winfo_toplevel())
        ctk.CTkLabel(self.qr_window, text="Leia o QR Code com o WhatsApp", font=("Arial", 20, "bold")).pack(pady=(20, 8))
        ctk.CTkLabel(self.qr_window, text="WhatsApp > Aparelhos conectados > Conectar aparelho").pack(pady=(0, 12))
        self.qr_ctk_image = ctk.CTkImage(light_image=image, dark_image=image, size=(340, 340))
        ctk.CTkLabel(self.qr_window, text="", image=self.qr_ctk_image).pack(pady=8)
        ctk.CTkButton(self.qr_window, text="Já li o QR Code — verificar", command=self.check_connection).pack(pady=10)
