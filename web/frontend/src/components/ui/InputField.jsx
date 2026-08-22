export function InputField({
  label,
  value,
  onChange,
  placeholder = "",
  type = "text",
  min,
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">
        {label}
      </span>
      <input
        type={type}
        min={min}
        className="w-full rounded-lg border border-slate-300 px-4 py-3 text-sm outline-none focus:border-indigo-600"
        placeholder={placeholder}
        value={value}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}