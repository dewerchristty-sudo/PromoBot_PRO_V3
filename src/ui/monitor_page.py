import math
import os
import sqlite3
import subprocess
import threading
import tkinter as tk
from datetime import datetime, timedelta
from tkinter import messagebox

import customtkinter as ctk

from src.core.monitor import MonitorRunner
from src.core.store_manager import StoreManager


class HunterStatusReader:
    """Leitura somente-leitura do estado real do Promotion Hunter."""

    @staticmethod
    def _hunter_db():
        conn = sqlite3.connect("promotion_hunter.db")
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _pipeline_db():
        conn = sqlite3.connect("promotion_hunter_offer_pipeline.db")
        conn.row_factory = sqlite3.Row
        return conn

    @classmethod
    def read(cls):
        """Retorna snapshot completo do Promotion Hunter ou None em caso de erro."""
        try:
            return {
                "scheduler": cls._scheduler_state(),
                "last_run": cls._last_run(),
                "pipeline": cls._pipeline_stats(),
                "deliveries": cls._delivery_stats(),
                "process_active": cls._is_process_active(),
                "live_delivery": cls._live_delivery(),
                "blocked_group": cls._blocked_group(),
                "timestamp": datetime.now().strftime("%H:%M:%S"),
            }
        except Exception:
            return None

    @classmethod
    def _scheduler_state(cls):
        try:
            conn = cls._hunter_db()
            row = conn.execute(
                "SELECT running FROM promotion_hunter_scheduler_state WHERE singleton_id=1"
            ).fetchone()
            conn.close()
            db_running = bool(row["running"]) if row else False
        except Exception:
            db_running = False

        process_active = cls._is_process_active()
        recent = cls._recent_run_seconds()

        if process_active and recent is not None and recent < 1200:
            return "active"
        if process_active:
            return "active"
        if db_running:
            return "active"
        return "stopped"

    @classmethod
    def _recent_run_seconds(cls):
        try:
            conn = cls._hunter_db()
            row = conn.execute(
                "SELECT MAX(started_at) as last_start FROM promotion_hunter_runs"
            ).fetchone()
            conn.close()
            if row and row["last_start"]:
                last = datetime.fromisoformat(row["last_start"])
                return (datetime.now(last.tzinfo) - last).total_seconds()
        except Exception:
            pass
        return None

    @classmethod
    def _is_process_active(cls):
        try:
            _flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            result = subprocess.run(
                ["powershell", "-Command",
                 "Get-Process python* -ErrorAction SilentlyContinue | "
                 "Where-Object { $_.CommandLine -like '*_start_multi_store*' } | "
                 "Select-Object -First 1"],
                capture_output=True, text=True, timeout=5,
                creationflags=_flags,
            )
            return "python" in result.stdout.lower()
        except Exception:
            return False

    @classmethod
    def _last_run(cls):
        try:
            conn = cls._hunter_db()
            row = conn.execute(
                "SELECT status, collected_count, unique_count, started_at, finished_at "
                "FROM promotion_hunter_runs ORDER BY started_at DESC LIMIT 1"
            ).fetchone()
            conn.close()
            if not row:
                return None
            return {
                "status": row["status"],
                "collected": row["collected_count"],
                "unique": row["unique_count"],
                "started": row["started_at"],
                "finished": row["finished_at"],
                "duration": cls._duration(row["started_at"], row["finished_at"]),
            }
        except Exception:
            return None

    @classmethod
    def _duration(cls, started, finished):
        if not started or not finished:
            return None
        try:
            s = datetime.fromisoformat(started)
            f = datetime.fromisoformat(finished)
            seconds = (f - s).total_seconds()
            if seconds < 60:
                return f"{seconds:.0f}s"
            return f"{seconds/60:.1f}min"
        except Exception:
            return None

    @classmethod
    def _pipeline_stats(cls):
        try:
            conn = cls._pipeline_db()
            row = conn.execute(
                "SELECT SUM(received_count) as recv, SUM(valid_count) as valid, "
                "SUM(approved_count) as approved, SUM(blocked_count) as blocked, "
                "SUM(duplicate_count) as dups, SUM(discarded_count) as disc "
                "FROM offer_pipeline_runs WHERE created_at > datetime('now', '-1 hour')"
            ).fetchone()
            conn.close()
            if not row:
                return None
            return {
                "received": int(row["recv"] or 0),
                "valid": int(row["valid"] or 0),
                "approved": int(row["approved"] or 0),
                "blocked": int(row["blocked"] or 0),
                "duplicates": int(row["dups"] or 0),
                "discarded": int(row["disc"] or 0),
            }
        except Exception:
            return None

    @classmethod
    def _delivery_stats(cls):
        try:
            conn = cls._hunter_db()
            sent = conn.execute(
                "SELECT COUNT(*) as cnt FROM promotion_hunter_delivery_queue "
                "WHERE status='sent' AND sent_at > datetime('now', '-1 hour')"
            ).fetchone()["cnt"]
            attempts = conn.execute(
                "SELECT COUNT(*) as cnt FROM promotion_hunter_delivery_attempts "
                "WHERE started_at > datetime('now', '-1 hour')"
            ).fetchone()["cnt"]
            conn.close()
            return {"sent_hour": int(sent), "attempts_hour": int(attempts)}
        except Exception:
            return None

    @classmethod
    def _live_delivery(cls):
        return os.getenv("PROMOTION_HUNTER_LIVE_DELIVERY", "false").strip().casefold() in (
            "true", "1", "yes", "on"
        )

    @classmethod
    def _blocked_group(cls):
        return "Casa & Ofertas (bloqueado)"  # ID real omitido da interface


class MonitorStatusPresenter:

    ERROR_STATUSES = {"failed", "partial_success"}

    @staticmethod
    def parse_datetime(value):
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        try:
            return datetime.fromisoformat(str(value))
        except (TypeError, ValueError):
            return None

    @classmethod
    def format_datetime(cls, value, empty="Ainda não executado"):
        parsed = cls.parse_datetime(value)
        return parsed.strftime("%d/%m/%Y às %H:%M:%S") if parsed else empty

    @classmethod
    def format_compact_datetime(cls, value, empty="Ainda não executado"):
        parsed = cls.parse_datetime(value)
        return parsed.strftime("%d/%m %H:%M") if parsed else empty

    @classmethod
    def next_execution(cls, monitor, now=None):
        if not bool(monitor["ativo"]):
            return "—", None
        last = cls.parse_datetime(monitor["ultima_execucao"])
        if last is None:
            return "Aguardando primeira execução", None
        interval = max(int(monitor["intervalo_minutos"] or 1), 1)
        expected = last + timedelta(minutes=interval)
        now = now or datetime.now(tz=expected.tzinfo)
        remaining = max(
            math.ceil((expected - now).total_seconds() / 60),
            0,
        )
        return cls.format_datetime(expected), remaining

    @staticmethod
    def configuration_status(monitor):
        return "🟢 ATIVO" if bool(monitor["ativo"]) else "⚪ PAUSADO"

    @staticmethod
    def action_text(monitor):
        return "Pausar" if bool(monitor["ativo"]) else "Ativar"

    @classmethod
    def last_result(cls, telemetry):
        if not telemetry:
            return "Sem informação disponível", ""
        labels = {
            "success": "🟢 SUCESSO",
            "partial_success": "🟠 SUCESSO PARCIAL",
            "zero_results": "⚪ SEM RESULTADOS",
            "failed": "🔴 ERRO",
            "running": "🟡 EM ANDAMENTO",
        }
        status = labels.get(telemetry.get("status"), "Sem informação disponível")
        errors = telemetry.get("errors") or ()
        return status, str(errors[0])[:240] if errors else ""

    @classmethod
    def summary(cls, monitors, snapshot, telemetry_by_id):
        active = sum(bool(item["ativo"]) for item in monitors)
        paused = len(monitors) - active
        errors = sum(
            bool(
                telemetry_by_id.get(item["id"])
                and telemetry_by_id[item["id"]].get("status")
                in cls.ERROR_STATUSES
            )
            for item in monitors
        )
        current_id = snapshot.get("current_monitor_id")
        return {
            "automatic_running": bool(snapshot.get("automatic_running")),
            "active": active,
            "paused": paused,
            "running": int(current_id is not None),
            "errors": errors,
            "current_id": current_id,
            "current_term": snapshot.get("current_monitor_term") or "",
        }


class MonitorPage(ctk.CTkFrame):

    REFRESH_MILLISECONDS = 4000
    ACTIVITY_LIMIT = 100

    def __init__(self, master, database, runner=None):
        super().__init__(master)
        self.database = database
        self.runner = runner or MonitorRunner(database)
        self.previous_progress_callback = self.runner.progress_callback
        self.runner.set_progress_callback(self.log_threadsafe)
        self.presenter = MonitorStatusPresenter()
        self.lojas = {}
        self.monitoramentos = []
        self.telemetry_by_id = {}
        self.refresh_job = None
        self.manual_monitor_ids = set()
        self.general_execution_active = False
        self.activity_lines = []
        self.activity_expanded = False
        self.expanded_monitor_ids = set()
        self.previous_visual_snapshot = None
        self.previous_cards_snapshot = None
        self.countdown_labels = {}
        self.summary_values = {}

        lojas_padrao = set(StoreManager.default_store_names())
        for nome in (
            StoreManager.stable_store_names()
            + StoreManager.experimental_store_names()
        ):
            self.lojas[nome] = tk.BooleanVar(value=nome in lojas_padrao)

        self.criar_interface()
        self.carregar()
        self.schedule_refresh()

    def criar_interface(self):
        ctk.CTkLabel(
            self,
            text="📋 Monitoramento",
            font=("Arial", 30, "bold"),
        ).pack(pady=(14, 2))
        ctk.CTkLabel(
            self,
            text="Acompanhe buscas automáticas e execute monitores individualmente.",
            font=("Arial", 13),
        ).pack(pady=(0, 8))

        # --- BLOCO: OPERAÇÃO AUTOMÁTICA (Promotion Hunter) ---
        self.hunter_frame = ctk.CTkFrame(self, fg_color="#1e2a1e")
        self.hunter_frame.pack(fill="x", padx=20, pady=(0, 8))

        hunter_header = ctk.CTkFrame(self.hunter_frame, fg_color="transparent")
        hunter_header.pack(fill="x", padx=10, pady=(6, 2))
        ctk.CTkLabel(
            hunter_header,
            text="🤖 Caçador Automático (Promotion Hunter)",
            font=("Arial", 15, "bold"),
            text_color="#8fdf8f",
        ).pack(side="left")
        self.hunter_values = {}
        cards_frame = ctk.CTkFrame(self.hunter_frame, fg_color="transparent")
        cards_frame.pack(fill="x", padx=6, pady=(0, 6))
        for col in range(8):
            cards_frame.grid_columnconfigure(col, weight=1)

        hunter_cards = (
            ("hunter_scheduler", "Scheduler"),
            ("hunter_status", "Promotion Hunter"),
            ("hunter_stores", "Lojas e fontes"),
            ("hunter_last", "Último ciclo"),
            ("hunter_pipeline", "Pipeline (1h)"),
            ("hunter_delivery", "Entregas (1h)"),
            ("hunter_security", "Segurança"),
            ("hunter_blocked", "Grupo bloqueado"),
        )
        for col, (key, title) in enumerate(hunter_cards):
            card = ctk.CTkFrame(cards_frame, fg_color="#1a2e1a")
            card.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 2, 0 if col == 7 else 2))
            ctk.CTkLabel(
                card, text=title, font=("Arial", 10, "bold"),
                text_color="#8fdf8f",
            ).pack(padx=5, pady=(4, 0))
            value = ctk.CTkLabel(
                card, text="—", font=("Arial", 12, "bold"),
                text_color="#d0d0d0", wraplength=130,
            )
            value.pack(padx=5, pady=(0, 4))
            self.hunter_values[key] = value

        self.summary_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.summary_frame.pack(fill="x", padx=20, pady=(0, 5))
        for column in range(6):
            self.summary_frame.grid_columnconfigure(column, weight=1)
        for column, (key, title) in enumerate((
            ("automatic", "🟢 Monitoramento"),
            ("monitors", "📋 Monitores"),
            ("running", "🟡 Executando"),
            ("errors", "🔴 Erros"),
            ("activity", "Última atividade"),
            ("next_check", "Próxima verificação"),
        )):
            card = ctk.CTkFrame(self.summary_frame, fg_color="#292f38")
            card.grid(
                row=0,
                column=column,
                sticky="nsew",
                padx=(0 if column == 0 else 3, 0 if column == 5 else 3),
            )
            ctk.CTkLabel(
                card,
                text=title,
                font=("Arial", 11, "bold"),
                text_color="#b8c1cc",
            ).pack(padx=6, pady=(5, 0))
            value = ctk.CTkLabel(
                card,
                text="—",
                font=("Arial", 13, "bold"),
                wraplength=145,
            )
            value.pack(padx=6, pady=(0, 5))
            self.summary_values[key] = value

        summary_footer = ctk.CTkFrame(self, fg_color="transparent")
        summary_footer.pack(fill="x", padx=20, pady=(0, 6))
        self.updated_label = ctk.CTkLabel(
            summary_footer, text="Atualizado: —", text_color="#9ba4af"
        )
        self.updated_label.pack(side="left")
        ctk.CTkButton(
            summary_footer,
            text="Atualizar status",
            width=118,
            height=28,
            command=self.carregar,
        ).pack(side="right")

        form = ctk.CTkFrame(self, fg_color="#24282f")
        form.pack(fill="x", padx=20, pady=(0, 6))
        form.grid_columnconfigure(0, weight=1)
        ctk.CTkLabel(
            form,
            text="Adicionar monitor",
            font=("Arial", 14, "bold"),
            anchor="w",
        ).grid(row=0, column=0, columnspan=3, sticky="ew", padx=10, pady=(6, 0))
        self.termo = ctk.CTkEntry(
            form, placeholder_text="Produto para monitorar...", height=34
        )
        self.termo.grid(row=1, column=0, sticky="ew", padx=(10, 8), pady=6)
        self.intervalo = ctk.CTkEntry(
            form, placeholder_text="Minutos", width=100, height=34
        )
        self.intervalo.insert(0, "30")
        self.intervalo.grid(row=1, column=1, padx=(0, 8), pady=6)
        ctk.CTkButton(
            form, text="Adicionar", width=105, command=self.adicionar
        ).grid(row=1, column=2, padx=(0, 10), pady=6)

        lojas_frame = ctk.CTkFrame(form, fg_color="transparent")
        lojas_frame.grid(
            row=2, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 6)
        )
        ctk.CTkLabel(
            lojas_frame, text="Lojas:", font=("Arial", 13, "bold")
        ).pack(side="left", padx=(0, 10))
        for nome, variavel in self.lojas.items():
            ctk.CTkCheckBox(
                lojas_frame, text=nome, variable=variavel, width=0
            ).pack(side="left", padx=(0, 12))

        controls = ctk.CTkFrame(self, fg_color="transparent")
        controls.pack(fill="x", padx=20, pady=(0, 6))
        automatic_controls = ctk.CTkFrame(controls, fg_color="#24282f")
        automatic_controls.pack(side="left", fill="y", padx=(0, 5))
        ctk.CTkLabel(
            automatic_controls,
            text="Controle automático",
            font=("Arial", 12, "bold"),
        ).pack(anchor="w", padx=8, pady=(4, 0))
        automatic_buttons = ctk.CTkFrame(
            automatic_controls, fg_color="transparent"
        )
        automatic_buttons.pack(padx=8, pady=(2, 6))
        ctk.CTkButton(
            automatic_buttons, text="▶ Iniciar", width=80, command=self.iniciar
        ).pack(side="left", padx=(0, 4))
        ctk.CTkButton(
            automatic_buttons, text="⏸ Parar", width=80, command=self.parar
        ).pack(side="left", padx=(0, 4))
        self.run_all_button = ctk.CTkButton(
            automatic_buttons,
            text="▶ Executar todos",
            width=122,
            command=self.executar_agora,
        )
        self.run_all_button.pack(side="left")

        management_controls = ctk.CTkFrame(controls, fg_color="#24282f")
        management_controls.pack(side="left", fill="y", padx=5)
        ctk.CTkLabel(
            management_controls,
            text="Gerenciamento",
            font=("Arial", 12, "bold"),
        ).pack(anchor="w", padx=8, pady=(4, 0))
        ctk.CTkButton(
            management_controls,
            text="Categorias padrão",
            width=135,
            command=self.adicionar_padrao,
        ).pack(padx=8, pady=(2, 6))

        selected_controls = ctk.CTkFrame(controls, fg_color="#24282f")
        selected_controls.pack(side="left", fill="both", expand=True, padx=(5, 0))
        ctk.CTkLabel(
            selected_controls,
            text="Monitor selecionado",
            font=("Arial", 12, "bold"),
        ).pack(anchor="w", padx=8, pady=(4, 0))
        selected_buttons = ctk.CTkFrame(
            selected_controls, fg_color="transparent"
        )
        selected_buttons.pack(fill="x", padx=8, pady=(2, 1))
        self.id_entry = ctk.CTkEntry(
            selected_buttons, placeholder_text="ID", width=65, height=32
        )
        self.id_entry.pack(side="left", padx=(0, 6))
        self.id_entry.bind("<KeyRelease>", lambda _event: self.update_id_action())
        self.toggle_button = ctk.CTkButton(
            selected_buttons,
            text="Ativar/Pausar",
            width=110,
            command=self.alternar,
        )
        self.toggle_button.pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            selected_buttons,
            text="🗑 Remover",
            width=90,
            fg_color="#8a1f1f",
            hover_color="#6f1717",
            command=self.remover,
        ).pack(side="left")

        self.selection_label = ctk.CTkLabel(
            selected_controls,
            text="Informe um ID para usar as ações alternativas.",
            anchor="w",
            text_color="#aeb6c1",
        )
        self.selection_label.pack(fill="x", padx=8, pady=(0, 4))

        self.activity_toggle_button = ctk.CTkButton(
            self,
            text="▼ Mostrar atividade da sessão",
            height=28,
            fg_color="#303640",
            hover_color="#3a424e",
            command=self.toggle_activity,
        )
        self.activity_toggle_button.pack(fill="x", padx=20, pady=(0, 4))

        self.activity_panel = ctk.CTkFrame(self)
        activity_header = ctk.CTkFrame(
            self.activity_panel, fg_color="transparent"
        )
        activity_header.pack(fill="x", padx=8, pady=(6, 0))
        ctk.CTkLabel(
            activity_header,
            text="Atividade da sessão",
            font=("Arial", 13, "bold"),
        ).pack(side="left")
        ctk.CTkButton(
            activity_header,
            text="Limpar visualização",
            width=120,
            command=self.clear_activity,
        ).pack(side="right")
        self.activity = ctk.CTkTextbox(
            self.activity_panel, wrap="word", height=110
        )
        self.activity.pack(fill="x", padx=8, pady=8)

        self.cards = ctk.CTkScrollableFrame(
            self, label_text="Monitores cadastrados"
        )
        self.cards.pack(fill="both", expand=True, padx=20, pady=(0, 10))

    def telemetry_for(self, monitor_id):
        service = self.runner.telemetry_service
        if service is None:
            return None
        return service.latest_monitor_result(monitor_id)

    def carregar(self):
        monitors = list(self.database.listar_monitoramentos())
        telemetry_by_id = {
            item["id"]: self.telemetry_for(item["id"])
            for item in monitors
        }
        snapshot = self.runner.status_snapshot()
        visual_snapshot = self.build_visual_snapshot(
            monitors, snapshot, telemetry_by_id
        )
        cards_snapshot = self.build_cards_snapshot(
            monitors, snapshot, telemetry_by_id
        )
        self.monitoramentos = monitors
        self.telemetry_by_id = telemetry_by_id
        self.render_hunter_status()
        if visual_snapshot != self.previous_visual_snapshot:
            self.render_summary(snapshot)
            self.previous_visual_snapshot = visual_snapshot
        else:
            self.update_updated_time()
        if cards_snapshot != self.previous_cards_snapshot:
            scroll_position = self.get_scroll_position()
            self.render_cards(snapshot)
            self.restore_scroll_position(scroll_position)
            self.previous_cards_snapshot = cards_snapshot
            self.update_id_action(show_missing=False)
        else:
            self.update_countdown_labels()

    def build_visual_snapshot(self, monitors, snapshot, telemetry_by_id):
        summary = self.presenter.summary(monitors, snapshot, telemetry_by_id)
        return (
            summary["automatic_running"],
            summary["active"],
            summary["paused"],
            summary["running"],
            summary["errors"],
            summary["current_id"],
            summary["current_term"],
            snapshot.get("last_activity_at"),
            snapshot.get("last_activity_message"),
            snapshot.get("next_loop_check_at"),
        )

    def build_cards_snapshot(self, monitors, snapshot, telemetry_by_id):
        monitor_data = tuple(
            (
                item["id"],
                item["termo"],
                item["lojas"],
                item["intervalo_minutos"],
                bool(item["ativo"]),
                item["ultima_execucao"],
                item["ultimo_total"],
                self.telemetry_snapshot(telemetry_by_id.get(item["id"])),
                item["id"] in self.manual_monitor_ids,
            )
            for item in monitors
        )
        return (
            monitor_data,
            snapshot.get("current_monitor_id"),
            snapshot.get("current_execution_started_at"),
            tuple(sorted(self.expanded_monitor_ids)),
        )

    @staticmethod
    def telemetry_snapshot(telemetry):
        if not telemetry:
            return None
        return (
            telemetry.get("execution_id"),
            telemetry.get("started_at"),
            telemetry.get("finished_at"),
            telemetry.get("aggregate_total"),
            telemetry.get("status"),
            tuple(telemetry.get("errors") or ()),
        )

    def render_summary(self, snapshot):
        summary = self.presenter.summary(
            self.monitoramentos, snapshot, self.telemetry_by_id
        )
        if summary["current_id"] is None:
            executing = "Nenhum"
        else:
            executing = (
                f"ID {summary['current_id']} — {summary['current_term']}"
            )
        last_activity = self.presenter.format_compact_datetime(
            snapshot.get("last_activity_at"), "Aguardando"
        )
        activity_message = snapshot.get("last_activity_message") or ""
        next_check = self.presenter.format_compact_datetime(
            snapshot.get("next_loop_check_at"),
            "Aguardando",
        )
        compact_activity = activity_message[:35]
        if len(activity_message) > 35:
            compact_activity += "…"
        self.summary_values["automatic"].configure(
            text="LIGADO" if summary["automatic_running"] else "DESLIGADO"
        )
        self.summary_values["monitors"].configure(
            text=f"{summary['active']} ativos\n{summary['paused']} pausados"
        )
        self.summary_values["running"].configure(text=executing)
        self.summary_values["errors"].configure(text=str(summary["errors"]))
        self.summary_values["activity"].configure(
            text=f"{last_activity}\n{compact_activity}".strip()
        )
        self.summary_values["next_check"].configure(text=next_check)
        self.update_updated_time()

    def render_hunter_status(self):
        """Atualiza os cartoes do Caçador Automático com dados reais."""
        if not hasattr(self, "hunter_values"):
            return
        data = HunterStatusReader.read()
        if data is None:
            self.hunter_values["hunter_scheduler"].configure(text="Erro")
            self.hunter_values["hunter_status"].configure(text="Indisponível")
            return

        # Scheduler
        sched_state = data["scheduler"]
        sched_display = {
            "active": "✅ ATIVO",
            "stopped": "⏸ PARADO",
        }.get(sched_state, f"❓ {sched_state}")
        self.hunter_values["hunter_scheduler"].configure(text=sched_display)

        # Promotion Hunter
        if data["process_active"]:
            self.hunter_values["hunter_status"].configure(text="🟢 Executando")
        else:
            self.hunter_values["hunter_status"].configure(text="Aguardando")

        # Lojas e fontes
        stores_text = "ML: 17\nAmazon: 7\nShopee: 6\nTotal: 30 fontes"
        self.hunter_values["hunter_stores"].configure(text=stores_text)

        # Último ciclo
        last = data["last_run"]
        if last:
            status_icon = {"success": "✅", "failed": "❌"}.get(last["status"], "❓")
            duration = last.get("duration") or ""
            last_text = (
                f"{status_icon} {last['collected']} coleta.\n"
                f"⏱ {duration}"
            )
        else:
            last_text = "Sem dados"
        self.hunter_values["hunter_last"].configure(text=last_text)

        # Pipeline
        pl = data["pipeline"]
        if pl:
            pl_text = (
                f"Receb.: {pl['received']}\n"
                f"Valid.: {pl['valid']}\n"
                f"Aprov.: {pl['approved']}\n"
                f"Bloq.: {pl['blocked']}\n"
                f"Dup.: {pl['duplicates']}"
            )
        else:
            pl_text = "—"
        self.hunter_values["hunter_pipeline"].configure(text=pl_text)

        # Entregas
        dl = data["deliveries"]
        if dl:
            dl_text = f"Enviadas: {dl['sent_hour']}\nTentat.: {dl['attempts_hour']}"
        else:
            dl_text = "—"
        self.hunter_values["hunter_delivery"].configure(text=dl_text)

        # Seguranca
        live = "LIVE: ✅" if data["live_delivery"] else "LIVE: ❌OFF"
        sched = "Sched: ✅" if data["scheduler"] == "active" else "Sched: ❌"
        self.hunter_values["hunter_security"].configure(
            text=f"{live}\n{sched}"
        )

        # Grupo bloqueado
        self.hunter_values["hunter_blocked"].configure(
            text=f"❌ {data['blocked_group']}"
        )

    def update_updated_time(self):
        self.updated_label.configure(
            text=f"Atualizado: {datetime.now().strftime('%H:%M:%S')}"
        )

    def render_cards(self, snapshot):
        self.countdown_labels = {}
        for widget in self.cards.winfo_children():
            widget.destroy()
        if not self.monitoramentos:
            ctk.CTkLabel(
                self.cards,
                text="Nenhum monitoramento cadastrado.",
            ).pack(pady=20)
            return
        for item in self.monitoramentos:
            self.create_monitor_card(item, snapshot)

    def create_monitor_card(self, monitor, snapshot):
        monitor_id = monitor["id"]
        telemetry = self.telemetry_by_id.get(monitor_id)
        expanded = monitor_id in self.expanded_monitor_ids
        is_running = (
            snapshot.get("current_monitor_id") == monitor_id
            or monitor_id in self.manual_monitor_ids
        )
        next_date, remaining = self.presenter.next_execution(monitor)
        result_label, error = self.presenter.last_result(telemetry)
        card = ctk.CTkFrame(self.cards, fg_color="#262b32")
        card.pack(fill="x", padx=5, pady=5)
        header = ctk.CTkFrame(card, fg_color="transparent")
        header.pack(fill="x", padx=10, pady=(8, 2))
        ctk.CTkLabel(
            header,
            text=str(monitor["termo"]),
            font=("Arial", 17, "bold"),
            wraplength=700,
            anchor="w",
        ).pack(side="left")
        visual_status = (
            "🟡 EXECUTANDO AGORA"
            if is_running else self.presenter.configuration_status(monitor)
        )
        ctk.CTkLabel(
            header, text=visual_status, font=("Arial", 13, "bold")
        ).pack(side="right")

        next_execution_text = (
            f"a partir de {next_date}"
            if remaining is not None else next_date
        )
        ctk.CTkLabel(
            card,
            text=f"ID {monitor_id}",
            text_color="#9ba4af",
            anchor="w",
        ).pack(fill="x", padx=10, pady=(0, 1))
        compact_store = str(monitor["lojas"] or "Nenhuma")
        if len(compact_store) > 80:
            compact_store = compact_store[:77] + "…"
        lines = [
            compact_store,
            "⏰ Última execução: "
            f"{self.presenter.format_compact_datetime(monitor['ultima_execucao'])}",
            f"📈 {monitor['ultimo_total']} produtos encontrados",
        ]
        if telemetry and telemetry.get("status") in self.presenter.ERROR_STATUSES:
            lines.append("🔴 Última tentativa com erro")
        ctk.CTkLabel(
            card,
            text="\n".join(lines),
            justify="left",
            anchor="w",
            wraplength=850,
        ).pack(fill="x", padx=10, pady=(1, 3))

        actions = ctk.CTkFrame(card, fg_color="transparent")
        actions.pack(fill="x", padx=10, pady=(2, 8))
        state = "disabled" if is_running else "normal"
        ctk.CTkButton(
            actions,
            text="▶ Executar",
            width=115,
            state=state,
            command=lambda data=dict(monitor): self.execute_card(data),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions,
            text="⏸ Pausar" if bool(monitor["ativo"]) else "▶ Ativar",
            width=80,
            state=state,
            command=lambda identifier=monitor_id: self.toggle_monitor(identifier),
        ).pack(side="left", padx=(0, 6))
        ctk.CTkButton(
            actions,
            text="🗑 Remover",
            width=80,
            state=state,
            fg_color="#8a1f1f",
            hover_color="#6f1717",
            command=lambda data=dict(monitor): self.remove_monitor(data),
        ).pack(side="left")
        ctk.CTkButton(
            actions,
            text="▲ Menos detalhes" if expanded else "▼ Mais detalhes",
            width=125,
            fg_color="#3a414b",
            hover_color="#464f5b",
            command=lambda identifier=monitor_id: self.toggle_details(identifier),
        ).pack(side="right")

        if not expanded:
            return
        details = ctk.CTkFrame(card, fg_color="#20242a")
        details.pack(fill="x", padx=10, pady=(0, 9))
        detail_lines = [
            f"Configuração: {self.presenter.configuration_status(monitor)}",
            f"Intervalo: {monitor['intervalo_minutos']} minutos",
            f"Lojas completas: {monitor['lojas'] or 'Nenhuma'}",
            f"Próximo monitoramento previsto: {next_execution_text}",
            f"Último resultado: {result_label}",
        ]
        if is_running:
            detail_lines.append(
                "Iniciado: "
                + self.presenter.format_datetime(
                    snapshot.get("current_execution_started_at"),
                    "Iniciando agora",
                )
            )
        if telemetry and telemetry.get("started_at"):
            detail_lines.append(
                "Última tentativa: "
                + self.presenter.format_datetime(telemetry["started_at"])
            )
        detail_lines.append(f"Erro: {error or '—'}")
        ctk.CTkLabel(
            details,
            text="\n".join(detail_lines),
            justify="left",
            anchor="w",
            wraplength=850,
        ).pack(fill="x", padx=9, pady=(7, 2))
        if remaining is not None:
            countdown = ctk.CTkLabel(
                details,
                text=f"⏳ Próxima execução em: {remaining} minuto(s)",
                anchor="w",
                font=("Arial", 12, "bold"),
            )
            countdown.pack(fill="x", padx=9, pady=(0, 7))
            self.countdown_labels[monitor_id] = countdown

    def toggle_details(self, monitor_id):
        scroll_position = self.get_scroll_position()
        if monitor_id in self.expanded_monitor_ids:
            self.expanded_monitor_ids.remove(monitor_id)
        else:
            self.expanded_monitor_ids.add(monitor_id)
        snapshot = self.runner.status_snapshot()
        self.render_cards(snapshot)
        self.previous_cards_snapshot = self.build_cards_snapshot(
            self.monitoramentos, snapshot, self.telemetry_by_id
        )
        self.restore_scroll_position(scroll_position)

    def update_countdown_labels(self):
        monitors = {item["id"]: item for item in self.monitoramentos}
        for monitor_id, label in tuple(self.countdown_labels.items()):
            monitor = monitors.get(monitor_id)
            if monitor is None or not label.winfo_exists():
                continue
            _date, remaining = self.presenter.next_execution(monitor)
            if remaining is not None:
                label.configure(
                    text=f"⏳ Próxima execução em: {remaining} minuto(s)"
                )

    def get_scroll_position(self):
        try:
            return self.cards._parent_canvas.yview()[0]
        except (AttributeError, IndexError, tk.TclError):
            return 0.0

    def restore_scroll_position(self, position):
        try:
            self.after_idle(
                lambda: self.cards._parent_canvas.yview_moveto(position)
            )
        except (AttributeError, tk.TclError):
            pass

    def schedule_refresh(self):
        if self.refresh_job is None and self.winfo_exists():
            self.refresh_job = self.after(
                self.REFRESH_MILLISECONDS,
                self._scheduled_refresh,
            )

    def _scheduled_refresh(self):
        self.refresh_job = None
        if self.winfo_exists():
            self.carregar()
            self.schedule_refresh()

    def toggle_activity(self):
        self.activity_expanded = not self.activity_expanded
        if self.activity_expanded:
            self.activity_toggle_button.configure(
                text="▲ Ocultar atividade da sessão"
            )
            self.activity_panel.pack(fill="x", padx=20, pady=(0, 6))
            self.cards.pack_forget()
            self.cards.pack(fill="both", expand=True, padx=20, pady=(0, 10))
            self.refresh_activity_widget()
        else:
            self.activity_toggle_button.configure(
                text="▼ Mostrar atividade da sessão"
            )
            self.activity_panel.pack_forget()

    def adicionar(self):
        lojas = self.lojas_selecionadas()
        if not lojas:
            messagebox.showerror(
                "Nenhuma loja",
                "Selecione ao menos uma loja para o monitoramento.",
            )
            return
        try:
            self.database.criar_monitoramento(
                self.termo.get(), self.intervalo.get(), ",".join(lojas)
            )
        except ValueError:
            messagebox.showerror(
                "Intervalo inválido",
                "Informe um intervalo em minutos. Exemplo: 30",
            )
            return
        self.termo.delete(0, "end")
        self.carregar()

    def iniciar(self):
        self.runner.start()
        self.carregar()

    def parar(self):
        self.runner.stop(wait=False)
        self.carregar()

    def executar_agora(self):
        if self.general_execution_active or self.runner.execution_lock.locked():
            messagebox.showinfo(
                "Monitoramento em andamento",
                "Já existe uma execução de monitoramento em andamento.",
            )
            return
        self.general_execution_active = True
        self.run_all_button.configure(state="disabled")
        self.append_activity("Execução manual de todos os ativos iniciada.")
        threading.Thread(target=self._executar_agora_thread, daemon=True).start()

    def _executar_agora_thread(self):
        try:
            total = self.runner.run_once()
            self.after(
                0,
                lambda: self.append_activity(
                    f"Execução manual concluída: {total} produto(s)."
                ),
            )
        except Exception as error:
            self.after(
                0,
                lambda message=str(error): messagebox.showerror(
                    "Falha no monitoramento", message
                ),
            )
        finally:
            self.after(0, self._finish_general_execution)

    def _finish_general_execution(self):
        self.general_execution_active = False
        self.run_all_button.configure(state="normal")
        self.carregar()

    def execute_card(self, monitor):
        monitor_id = monitor["id"]
        if (
            monitor_id in self.manual_monitor_ids
            or self.runner.execution_lock.locked()
        ):
            messagebox.showinfo(
                "Monitoramento em andamento",
                "Já existe uma execução de monitoramento em andamento.",
            )
            return
        self.manual_monitor_ids.add(monitor_id)
        self.append_activity(
            f"Iniciando monitor {monitor_id} — {monitor['termo']}"
        )
        self.carregar()
        threading.Thread(
            target=self._execute_card_thread,
            args=(monitor,),
            daemon=True,
        ).start()

    def _execute_card_thread(self, monitor):
        try:
            total = self.runner.run_monitor_once(monitor)
            self.after(
                0,
                lambda: self.append_activity(
                    f"Monitor {monitor['id']} concluído: {total} produto(s)."
                ),
            )
        except Exception as error:
            self.after(
                0,
                lambda message=str(error): messagebox.showerror(
                    "Falha no monitoramento", message
                ),
            )
        finally:
            self.after(0, lambda: self._finish_card_execution(monitor["id"]))

    def _finish_card_execution(self, monitor_id):
        self.manual_monitor_ids.discard(monitor_id)
        self.carregar()

    def adicionar_padrao(self):
        lojas = self.lojas_selecionadas()
        if not lojas:
            messagebox.showerror(
                "Nenhuma loja",
                "Selecione ao menos uma loja para as categorias padrão.",
            )
            return
        try:
            criados = self.database.criar_monitoramentos_padrao(
                self.intervalo.get(), ",".join(lojas)
            )
        except ValueError:
            messagebox.showerror(
                "Intervalo inválido",
                "Informe um intervalo em minutos. Exemplo: 60",
            )
            return
        messagebox.showinfo(
            "Categorias padrão",
            f"{criados} novo(s) monitoramento(s) criado(s).",
        )
        self.carregar()

    def lojas_selecionadas(self):
        return [nome for nome, variable in self.lojas.items() if variable.get()]

    def find_monitor(self, monitor_id):
        return next(
            (item for item in self.monitoramentos if item["id"] == monitor_id),
            None,
        )

    def monitoramento_id(self, show_error=True):
        text = self.id_entry.get().strip()
        if not text:
            return None
        try:
            return int(text)
        except ValueError:
            if show_error:
                messagebox.showerror("ID inválido", "Informe o ID numérico.")
            return None

    def update_id_action(self, show_missing=True):
        monitor_id = self.monitoramento_id(show_error=False)
        if monitor_id is None:
            self.toggle_button.configure(text="Ativar/Pausar")
            self.selection_label.configure(
                text="Informe um ID para usar as ações alternativas."
            )
            return
        monitor = self.find_monitor(monitor_id)
        if monitor is None:
            self.toggle_button.configure(text="Ativar/Pausar")
            self.selection_label.configure(
                text=f"Monitor ID {monitor_id} não encontrado."
            )
            if show_missing:
                return
            return
        action = self.presenter.action_text(monitor)
        self.toggle_button.configure(text=action)
        self.selection_label.configure(
            text=(
                f"Monitor selecionado: ID {monitor_id} — {monitor['termo']} | "
                f"Ação disponível: {action}"
            )
        )

    def alternar(self):
        monitor_id = self.monitoramento_id()
        if monitor_id is None:
            return
        monitor = self.find_monitor(monitor_id)
        if monitor is None:
            messagebox.showerror(
                "Monitor não encontrado",
                f"Monitor ID {monitor_id} não encontrado.",
            )
            return
        self.toggle_monitor(monitor_id)

    def toggle_monitor(self, monitor_id):
        self.database.alternar_monitoramento(monitor_id)
        self.carregar()

    def remover(self):
        monitor_id = self.monitoramento_id()
        if monitor_id is None:
            return
        monitor = self.find_monitor(monitor_id)
        if monitor is None:
            messagebox.showerror(
                "Monitor não encontrado",
                f"Monitor ID {monitor_id} não encontrado.",
            )
            return
        self.remove_monitor(dict(monitor))

    def remove_monitor(self, monitor):
        confirmed = messagebox.askyesno(
            "Remover monitoramento",
            f"Remover o monitor ID {monitor['id']} — {monitor['termo']}?",
        )
        if not confirmed:
            return
        self.database.remover_monitoramento(monitor["id"])
        self.carregar()

    def append_activity(self, text):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.activity_lines.append(f"{timestamp} — {text}")
        self.activity_lines = self.activity_lines[-self.ACTIVITY_LIMIT:]
        if self.activity_expanded:
            self.refresh_activity_widget()

    def refresh_activity_widget(self):
        self.activity.delete("1.0", "end")
        self.activity.insert("end", "\n".join(self.activity_lines))
        self.activity.see("end")

    def clear_activity(self):
        self.activity_lines.clear()
        if self.activity_expanded:
            self.activity.delete("1.0", "end")

    def log_threadsafe(self, text):
        self.after(0, lambda: self.append_activity(str(text)))

    def destroy(self):
        self.cancel_scheduled_refresh()
        if self.runner.progress_callback == self.log_threadsafe:
            self.runner.set_progress_callback(self.previous_progress_callback)
        super().destroy()

    def cancel_scheduled_refresh(self):
        if self.refresh_job is None:
            return
        try:
            self.after_cancel(self.refresh_job)
        except Exception:
            pass
        self.refresh_job = None
