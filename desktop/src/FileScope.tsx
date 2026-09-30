import { useRef, useState } from "react";

/** Checkmarks are the action scope; highlighted rows are the keyboard scope. */
export function FileScope({
  names,
  selected,
  onChange,
  query = "",
  disabled = false,
}: {
  names: string[];
  selected: string[];
  onChange: (names: string[]) => void;
  query?: string;
  disabled?: boolean;
}) {
  const visible = names.filter((name) =>
    name.toLowerCase().includes(query.toLowerCase()),
  );
  const [rows, setRows] = useState<string[]>([]);
  const anchor = useRef("");
  const gesture = useRef({ shift: false, control: false });
  function apply(scope: string[], checked: boolean) {
    const next = new Set(selected);
    for (const name of scope) checked ? next.add(name) : next.delete(name);
    onChange(names.filter((name) => next.has(name)));
  }
  function toggle(name: string, checked: boolean) {
    const { shift, control } = gesture.current;
    gesture.current = { shift: false, control: false };
    if (shift) {
      const from = Math.max(0, visible.indexOf(anchor.current)),
        to = visible.indexOf(name);
      const scope = visible.slice(Math.min(from, to), Math.max(from, to) + 1);
      setRows(control ? [...new Set([...rows, ...scope])] : scope);
      apply(scope, checked);
    } else {
      setRows(
        control
          ? rows.includes(name)
            ? rows.filter((row) => row !== name)
            : [...rows, name]
          : [name],
      );
      anchor.current = name;
      apply([name], checked);
    }
  }
  return (
    <div className="workflow-files" role="group" aria-label="Workflow files">
      {visible.map((name) => (
        <label
          key={name}
          className={rows.includes(name) ? "selected-row" : ""}
          onPointerDown={(event) => {
            gesture.current = {
              shift: event.shiftKey,
              control: event.ctrlKey || event.metaKey,
            };
          }}
        >
          <input
            type="checkbox"
            disabled={disabled}
            checked={selected.includes(name)}
            onChange={(event) => toggle(name, event.target.checked)}
            onKeyDown={(event) => {
              if (
                (event.ctrlKey || event.metaKey) &&
                event.key.toLowerCase() === "a"
              ) {
                event.preventDefault();
                setRows(visible);
                apply(visible, true);
              } else if (event.key === " ") {
                event.preventDefault();
                apply(
                  rows.includes(name)
                    ? rows.filter((row) => visible.includes(row))
                    : [name],
                  !selected.includes(name),
                );
              }
            }}
          />
          <span>{name}</span>
        </label>
      ))}
    </div>
  );
}
