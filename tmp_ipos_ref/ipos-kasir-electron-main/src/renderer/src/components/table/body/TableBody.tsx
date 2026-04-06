import React, { useEffect, useRef } from 'react';
import { FaTrashAlt } from 'react-icons/fa';
import { formatToIDR } from '../../../utils/utils';
import { TableCell } from '../cell/TableCell';

interface TableBodyProps {
  initialDatas: any[];
  focusedCell: number | null;
  isEdit: boolean;
  fields: string[];
  onDelete?: (id: number) => Promise<void>;
  onCellChange: (id: number, field: string, value: string) => void;
  onSelectChange?: (id: any, field: any, value: any) => void;
  setFocusedCell: (index: number | null) => void;
  rowEnter?: (id: number) => void | null;
}

const TableBody = React.forwardRef<HTMLTableSectionElement, TableBodyProps>(
  ({ initialDatas, focusedCell, isEdit, fields, onDelete, onCellChange, onSelectChange, setFocusedCell, rowEnter }, ref) => {
    const datas = initialDatas;
    const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

    const handleKeyDown = (id?: number | null, field?: string | null, event?: any) => {
      if (event.key === 'Enter') {
        if (rowEnter) return focusedCell != null && rowEnter(datas[focusedCell].id ?? 0);
        const value = event.currentTarget.value;
        if (id && field) onCellChange(id, field, value.toUpperCase());
      }
    };

    const filterContent = (data: any, field: any) => {
      if (field.includes('customers')) return data.customers_name == null ? 'UMUM' : data.customers_name;
      if (field.includes('date')) return new Date(data[field]).toLocaleDateString('id-ID', { year: 'numeric', month: 'long', day: 'numeric' }) + ', Pukul: '
        + new Date(data[field]).toLocaleTimeString('id-ID', { hour: '2-digit', minute: '2-digit' });
      if (field.includes('price')) return typeof data[field] === 'number' ? formatToIDR(data[field]) : '';
      if (field === 'is_stock_variant') return data[field] === 1 ? 'SATUAN' : 'BARANG';
      return data[field];
    };

    useEffect(() => {
      isEdit && inputRefs.current[0] != null ? inputRefs.current[0]?.focus() : inputRefs.current[1]?.focus();
      if (rowEnter != undefined) {
        window.addEventListener('keydown', (e) => { handleKeyDown(null, null, e) });
      }
      return () => {
        rowEnter = undefined;
        window.removeEventListener('keydown', (e) => { handleKeyDown(null, null, e) });
      };
    }, [focusedCell])

    return (
      <tbody ref={ref}>
        {datas && datas.length > 0 ? (
          datas.map((data: any, index: number) => (
            <tr key={index} onClick={() => { rowEnter && rowEnter(data.id); }} onMouseEnter={() => { isEdit && setFocusedCell(index); }} onMouseLeave={() => { isEdit && setFocusedCell(0); }}>
              <TableCell
                className="w-0"
                name='index'
                isSelected={focusedCell === index}
                index={index}
                content={index + 1}
                isEditable={false}
              />
              {fields
                .filter(field => field !== 'no')
                .map((field, colIndex) => {
                  if (!inputRefs.current[colIndex]) {
                    inputRefs.current[colIndex] = null;
                  }

                  return (
                    <TableCell
                      ref={(el) => inputRefs.current[colIndex] = el}
                      key={colIndex}
                      data={data}
                      isSelected={focusedCell === index}
                      index={index}
                      isEditable={isEdit && focusedCell === index && !['products_name', 'units_name', 'stock'].includes(field)}
                      name={field}
                      content={filterContent(data, field)}
                      onKeyDown={(event) => handleKeyDown(data.id, field, event)}
                      onSelectChange={onSelectChange}
                      rowEnter={rowEnter}
                    />
                  );
                })}
              {isEdit && rowEnter == null && (
                <TableCell
                  isSelected={focusedCell === index}
                  index={index}
                  name='action'
                  className="w-[10px]"
                  isEditable={false}
                  content={
                    <div className="flex gap-x-4 items-center">
                      <button onClick={(): Promise<void> => (onDelete as (id: number) => Promise<void>)(data.id)} className="bg-red-500 px-4 py-2 rounded">
                        <FaTrashAlt className="text-white" size={16} />
                      </button>
                    </div>
                  }
                />
              )}
            </tr>
          ))
        ) : (
          <tr>
            <td colSpan={fields.length} className="p-2 text-center text-gray-500">
              Tidak ada data
            </td>
          </tr>
        )}
      </tbody>
    );
  }
);

export { TableBody };