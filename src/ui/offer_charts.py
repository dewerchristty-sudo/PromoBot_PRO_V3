import tkinter as tk

import customtkinter as ctk


class OfferChartCanvas(ctk.CTkFrame):
    """Gráfico leve baseado no Canvas nativo do Tk."""

    def __init__(self, master, height=190):
        super().__init__(master)
        self.title_label = ctk.CTkLabel(
            self,
            text="Gráfico",
            font=("Arial", 14, "bold"),
            anchor="w",
        )
        self.title_label.pack(fill="x", padx=10, pady=(8, 2))
        self.canvas = tk.Canvas(
            self,
            height=height,
            background="#242424",
            highlightthickness=0,
        )
        self.canvas.pack(fill="both", expand=True, padx=6, pady=(0, 6))
        self.series = None
        self.canvas.bind("<Configure>", lambda _event: self.redraw())

    def set_series(self, series):
        self.series = series
        self.title_label.configure(text=series.title)
        self.redraw()

    def redraw(self):
        self.canvas.delete("all")
        if not self.series or not self.series.values:
            self.canvas.create_text(
                12, 20, text="Sem dados", fill="#aaaaaa", anchor="w"
            )
            return

        width = max(self.canvas.winfo_width(), 280)
        height = max(self.canvas.winfo_height(), 150)
        left, right, top, bottom = 38, 12, 12, 30
        plot_width = width - left - right
        plot_height = height - top - bottom
        maximum = max(max(self.series.values), 1)
        self.canvas.create_line(
            left, top, left, top + plot_height,
            left + plot_width, top + plot_height,
            fill="#666666",
        )

        if self.series.kind == "line":
            self.draw_line(
                left, top, plot_width, plot_height, maximum
            )
        else:
            self.draw_bars(
                left, top, plot_width, plot_height, maximum
            )

    def draw_bars(self, left, top, width, height, maximum):
        count = len(self.series.values)
        slot = width / max(count, 1)
        bar_width = max(min(slot * 0.62, 42), 4)
        for index, value in enumerate(self.series.values):
            x = left + slot * index + slot / 2
            bar_height = (value / maximum) * height
            self.canvas.create_rectangle(
                x - bar_width / 2,
                top + height - bar_height,
                x + bar_width / 2,
                top + height,
                fill=self.series.color,
                outline="",
            )
            self.canvas.create_text(
                x,
                top + height - bar_height - 8,
                text=f"{value:g}",
                fill="#eeeeee",
                font=("Arial", 8),
            )
            label = self.series.labels[index][:10]
            self.canvas.create_text(
                x,
                top + height + 13,
                text=label,
                fill="#cccccc",
                font=("Arial", 8),
            )

    def draw_line(self, left, top, width, height, maximum):
        count = len(self.series.values)
        points = []
        for index, value in enumerate(self.series.values):
            x = left + (
                width * index / max(count - 1, 1)
            )
            y = top + height - (value / maximum) * height
            points.extend((x, y))
            self.canvas.create_oval(
                x - 3, y - 3, x + 3, y + 3,
                fill=self.series.color,
                outline="",
            )
            if index % max(count // 6, 1) == 0:
                self.canvas.create_text(
                    x,
                    top + height + 13,
                    text=self.series.labels[index][:8],
                    fill="#cccccc",
                    font=("Arial", 8),
                )
        if len(points) >= 4:
            self.canvas.create_line(
                *points,
                fill=self.series.color,
                width=2,
                smooth=True,
            )
