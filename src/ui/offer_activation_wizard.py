import getpass
import threading
from tkinter import filedialog, messagebox, simpledialog

import customtkinter as ctk

from src.offers.activation import OfferActivationFlags
from src.offers.activation_control import (
    CANARY_SAFE_5_PERCENT,
    SAFE_CONFIRMATION,
    OfferActivationManager,
    OfferPreflight,
)
from src.offers.activation_report import OfferActivationReport


class OfferActivationWizard(ctk.CTkFrame):
    """Assistente explícito; nunca ativa durante construção ou atualização."""

    def __init__(self, master, repository):
        super().__init__(master)
        self.repository = repository
        self.manager = OfferActivationManager(repository)
        self.create_interface()
        self.refresh()

    def create_interface(self):
        ctk.CTkLabel(
            self, text="Ativação Controlada",
            font=("Arial", 24, "bold"),
        ).pack(anchor="w", padx=14, pady=(12, 4))
        ctk.CTkLabel(
            self,
            text=(
                "Perfil recomendado: CANARY_SAFE_5_PERCENT — 5%, "
                "score 90, 1/h, 3/dia, rollback ativo"
            ),
        ).pack(anchor="w", padx=14)
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        buttons.pack(fill="x", padx=10, pady=8)
        for text, command, color in (
            ("Executar pré-verificações", self.preflight_async, None),
            ("Iniciar Dry Run", self.start_dry_run, "#2878b8"),
            ("Ativar Canary Real", self.start_real, "#b87520"),
            ("DESATIVAR IMEDIATAMENTE", self.stop_now, "#b33131"),
            ("Exportar CSV", self.export_csv, None),
            ("Exportar JSON", self.export_json, None),
        ):
            options = {"text": text, "command": command}
            if color:
                options["fg_color"] = color
            ctk.CTkButton(buttons, **options).pack(
                side="left", padx=4, pady=4
            )
        self.state = ctk.CTkTextbox(self, height=130)
        self.state.pack(fill="x", padx=14, pady=6)
        self.checks = ctk.CTkTextbox(self)
        self.checks.pack(fill="both", expand=True, padx=14, pady=(0, 12))

    def refresh(self):
        flags = OfferActivationFlags.from_environment()
        session = self.repository.current_activation_session()
        health = self.repository.activation_health()
        latest = self.repository.read_one("""
            SELECT reason, created_at FROM offer_canary_auto_stops
            ORDER BY id DESC LIMIT 1
        """)
        self.state.delete("1.0", "end")
        self.state.insert(
            "end",
            f"Modo: {flags.mode}\nScheduler ativo: "
            f"{flags.intelligent_scheduler_enabled}\n"
            f"Canary: {flags.canary_percent}% | Score: "
            f"{flags.minimum_score_to_send} | "
            f"Limites: {flags.max_send_per_hour}/h e "
            f"{flags.max_send_per_day}/dia\n"
            f"Dry Run: {flags.dry_run_transport} | Rollback: "
            f"{flags.enable_rollback}\n"
            f"Sessão: {session['status'] if session else 'nenhuma'} | "
            f"Pendências duplicadas: {health['pending_duplicates']}\n"
            f"Último Auto-Stop: {latest['reason'] if latest else 'nenhum'}"
        )

    def preflight_async(self):
        self.checks.delete("1.0", "end")
        self.checks.insert("end", "Verificando...\n")

        def worker():
            try:
                checks = OfferPreflight(self.repository).run(
                    CANARY_SAFE_5_PERCENT.flags()
                )
                self.after(0, lambda: self.show_checks(checks))
            except Exception as error:
                self.after(0, lambda: self.show_error(str(error)))

        threading.Thread(target=worker, daemon=True).start()

    def show_checks(self, checks):
        self.checks.delete("1.0", "end")
        for check in checks:
            icon = "OK" if check.passed else "BLOQUEADO"
            self.checks.insert(
                "end", f"[{icon}] {check.name}: {check.detail}\n"
            )

    def show_error(self, error):
        self.checks.delete("1.0", "end")
        self.checks.insert("end", f"Falha: {error}")

    def start_dry_run(self):
        confirmation = simpledialog.askstring(
            "Confirmação", 'Digite "CONFIRMO DRY RUN":', parent=self
        )
        self.activate(confirmation or "", False)

    def start_real(self):
        confirmation = simpledialog.askstring(
            "Confirmação forte",
            f'Digite exatamente:\n{SAFE_CONFIRMATION}',
            parent=self,
        )
        self.activate(confirmation or "", True)

    def activate(self, confirmation, real):
        try:
            session = self.manager.activate(
                CANARY_SAFE_5_PERCENT,
                getpass.getuser(),
                confirmation,
                real_transport=real,
            )
            messagebox.showinfo(
                "Ativação", f"Sessão iniciada: {session}", parent=self
            )
            self.refresh()
        except Exception as error:
            messagebox.showerror("Ativação bloqueada", str(error), parent=self)

    def stop_now(self):
        reason = simpledialog.askstring(
            "Desativação", "Informe o motivo:", parent=self
        )
        if not reason:
            return
        if not messagebox.askyesno(
            "Confirmar",
            "Desativar o Scheduler Inteligente imediatamente?",
            parent=self,
        ):
            return
        self.manager.deactivate(getpass.getuser(), reason)
        messagebox.showinfo(
            "Desativado", "Fluxo legado preservado.", parent=self
        )
        self.refresh()

    def export_csv(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")]
        )
        if path:
            OfferActivationReport(self.repository).export_csv(path)

    def export_json(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")]
        )
        if path:
            OfferActivationReport(self.repository).export_json(path)
