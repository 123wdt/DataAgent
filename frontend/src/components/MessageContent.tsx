// 消息渲染：把 agent 返回的消息渲染为 文本 + 图表 混排
import ChartBlock from "./ChartBlock";

export interface ContentBlock {
  type: "text" | "chart" | "tool" | "table";
  text?: string;
  option?: any;
  name?: string;
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
}

function renderMarkdown(text: string): string {
  // 简单的行级渲染：标题 / 列表 / 表格 / 加粗 / 代码
  const lines = text.split("\n");
  let html = "";
  let inList = false;
  let inTable = false;

  const closeList = () => {
    if (inList) {
      html += "</ul>";
      inList = false;
    }
  };

  for (let raw of lines) {
    const line = raw.trimEnd();

    // 表格分隔行
    if (/^\s*\|?[\s:|-]+\|?\s*$/.test(line) && line.includes("---")) continue;
    // 表格行
    if (line.startsWith("|")) {
      const cells = line
        .split("|")
        .filter((_, i, a) => i > 0 && i < a.length - 1 || line.startsWith("|") && i === 0)
        .map((c) => `<td>${escapeHtml(c.trim())}</td>`)
        .join("");
      if (!inTable) {
        html += "<table><tbody>";
        inTable = true;
      } else {
        html = html.replace(/<tbody>$/, "<tbody>");
      }
      html += `<tr>${cells}</tr>`;
      continue;
    } else {
      if (inTable) {
        html += "</tbody></table>";
        inTable = false;
      }
    }

    if (/^#{1,6}\s/.test(line)) {
      closeList();
      const level = line.match(/^#+/)![0].length;
      html += `<h${level}>${escapeHtml(line.replace(/^#+\s*/, ""))}</h${level}>`;
    } else if (/^[-*•]\s/.test(line)) {
      if (!inList) {
        html += "<ul>";
        inList = true;
      }
      html += `<li>${escapeHtml(line.replace(/^[-*•]\s*/, ""))}</li>`;
    } else if (/^```/.test(line)) {
      closeList();
      html += "<pre class='code'>";
    } else if (line.trim() === "") {
      closeList();
      html += "<br/>";
    } else {
      closeList();
      let t = escapeHtml(line);
      // 加粗
      t = t.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
      html += `<p>${t}</p>`;
    }
  }
  if (inList) html += "</ul>";
  if (inTable) html += "</tbody></table>";
  return html;
}

export default function MessageContent({ blocks }: { blocks: ContentBlock[] }) {
  return (
    <div className="msg-content">
      {blocks.map((b, i) => {
        if (b.type === "chart" && b.option) {
          return <ChartBlock key={i} option={b.option} />;
        }
        if (b.type === "tool") {
          return (
            <div key={i} className="tool-chip">
              🔧 {b.name}
            </div>
          );
        }
        if (b.type === "table" && b.option) {
          return <ChartBlock key={i} option={b.option} height={280} />;
        }
        // text
        return (
          <div
            key={i}
            className="text-block"
            dangerouslySetInnerHTML={{ __html: renderMarkdown(b.text ?? "") }}
          />
        );
      })}
    </div>
  );
}
