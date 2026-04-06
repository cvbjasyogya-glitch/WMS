import React, { KeyboardEvent, useEffect, useState, forwardRef } from 'react';

interface TableCellProps {
  isSelected: boolean;
  isEditable: boolean;
  index: number;
  name: string;
  content: React.ReactNode;
  onKeyDown?: (e: KeyboardEvent<HTMLElement>) => void;
  className?: string;
  data?: any;
  rowEnter?: (id: number) => void | null;
  onSelectChange?: (id: number, field: string, value: any) => void;
}

const TableCell = forwardRef<HTMLInputElement, TableCellProps>(({
  isSelected,
  isEditable,
  name,
  content,
  onKeyDown,
  className,
  data,
  onSelectChange,
  rowEnter
}, ref) => {
  const [categories, setCategories] = useState<any[]>([]);

  useEffect(() => {
    const fetchCategories = async () => {
      try {
        const response = await (window.api as any).category.get();
        if (response && response.success) {
          setCategories(response.data);
        } else {
          console.error('Failed to fetch categories:', response.error);
        }
      } catch (error) {
        console.error('Error fetching categories:', error);
      }
    };

    if (name === 'categories_name') {
      fetchCategories();
    }
  }, [name]);

  const inputType = name.includes('price') ? 'number' : 'text';

  return (
    <td className={`border p-4 ${isSelected ? 'bg-blue-100' : ''} ${className}`}>
      {isEditable && rowEnter == null ? (
        name === 'categories_name' ? (
          <select
            name='category_id'
            defaultValue={data['category_id'] || ''}
            onChange={(e) => onSelectChange && onSelectChange(data.id, 'category_id', e.target.value)}
            className="w-full border border-gray-300 rounded p-1"
          >
            <option value="" disabled>Select a category</option>
            {categories.map((category) => (
              <option key={category.id} value={category.id}>
                {category.name}
              </option>
            ))}
          </select>
        ) : name === 'is_stock_variant' ? (
          <select
            name='is_stock_variant'
            defaultValue={data['is_stock_variant'] || 0}
            onChange={(e) => onSelectChange && onSelectChange(data.id, name, e.target.value)}
            className="w-full border border-gray-300 rounded p-1"
          >
            <option value="" disabled>Pilih tipe satuan</option>
            <option value="1">Satuan</option><option value="0">Barang</option>
          </select>
        ) : (
          <input
            ref={ref}
            type={inputType}
            defaultValue={data[name]}
            onKeyDown={onKeyDown}
            className="w-full border border-gray-300 rounded p-1"
            name={name}
          />
        )
      ) : (
        content
      )}
    </td>
  );
});

export { TableCell };