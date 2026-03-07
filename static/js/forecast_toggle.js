(function () {
  const data = window.moneyScheduleData || { days: [] };
  const bufferFloor = Number(data.buffer_floor || data.floor || 0);
  const atRiskDates = new Set(data.at_risk_dates || []);
  const sections = document.querySelectorAll(".view-section");
  const buttons = document.querySelectorAll(".toggle-btn");
  let timelineRendered = false;

  function showSection(id) {
    sections.forEach((section) => {
      if (section.id === id) {
        section.classList.remove("hidden");
      } else {
        section.classList.add("hidden");
      }
    });

    buttons.forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.target === id);
    });

    if (id === "timeline-view" && !timelineRendered) {
      renderTimeline();
      timelineRendered = true;
    }
  }

  function renderTimeline() {
    if (!data.days || data.days.length === 0) {
      return;
    }

    const canvas = document.getElementById("forecast-timeline");
    if (!canvas) return;

    const ctx = canvas.getContext("2d");
    const width = canvas.width;
    const height = canvas.height;
    ctx.clearRect(0, 0, width, height);

    const points = data.days.map((day, index) => {
      return {
        x: index,
        closing: Number(day.closing_balance),
        date: day.date,
      };
    });

    const closingValues = points.map((p) => p.closing);
    let minClosing = Math.min(...closingValues);
    let maxClosing = Math.max(...closingValues);
    if (bufferFloor > 0) {
      minClosing = Math.min(minClosing, bufferFloor);
      maxClosing = Math.max(maxClosing, bufferFloor);
    }
    const verticalPadding = 40;

    function scaleY(value) {
      if (maxClosing === minClosing) return height / 2;
      const ratio = (value - minClosing) / (maxClosing - minClosing);
      return height - verticalPadding - ratio * (height - verticalPadding * 2);
    }

    const horizontalStep = width / Math.max(points.length - 1, 1);

    ctx.strokeStyle = "#cbd5e0";
    ctx.beginPath();
    ctx.moveTo(0, height - verticalPadding);
    ctx.lineTo(width, height - verticalPadding);
    ctx.stroke();

    if (bufferFloor > 0) {
      const floorY = scaleY(bufferFloor);
      ctx.save();
      ctx.setLineDash([6, 4]);
      ctx.strokeStyle = "#b22222";
      ctx.beginPath();
      ctx.moveTo(0, floorY);
      ctx.lineTo(width, floorY);
      ctx.stroke();
      ctx.fillStyle = "#b22222";
      ctx.fillText(`Floor ₩${bufferFloor.toLocaleString()}`, 10, floorY - 6);
      ctx.restore();
    }

    ctx.strokeStyle = "#3182ce";
    ctx.lineWidth = 2;
    ctx.beginPath();
    points.forEach((point, index) => {
      const x = index * horizontalStep;
      const y = scaleY(point.closing);
      if (index === 0) {
        ctx.moveTo(x, y);
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.stroke();

    points.forEach((point, index) => {
      const x = index * horizontalStep;
      const y = scaleY(point.closing);
      ctx.fillStyle = atRiskDates.has(point.date) ? "#c53030" : "#3182ce";
      ctx.beginPath();
      ctx.arc(x, y, 4, 0, Math.PI * 2);
      ctx.fill();
    });

    ctx.fillStyle = "#4a5568";
    ctx.font = "12px 'Segoe UI', Arial, sans-serif";

    const markerY = scaleY(points[points.length - 1].closing);
    const markerX = (points.length - 1) * horizontalStep;
    ctx.fillText(
      `Close ₩${Number(points[points.length - 1].closing).toLocaleString()}`,
      Math.max(markerX - 100, 10),
      markerY - 10
    );
  }

  function initCalendar() {
    const cells = document.querySelectorAll(".calendar-cell");
    cells.forEach((cell) => {
      cell.addEventListener("click", () => {
        const popup = cell.querySelector(".calendar-items");
        if (popup) {
          popup.classList.toggle("hidden");
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    initCalendar();

    buttons.forEach((btn) => {
      btn.addEventListener("click", () => {
        showSection(btn.dataset.target);
      });
    });

    if (data.view) {
      showSection(`${data.view}-view`);
    } else {
      showSection("table-view");
    }
  });
})();
