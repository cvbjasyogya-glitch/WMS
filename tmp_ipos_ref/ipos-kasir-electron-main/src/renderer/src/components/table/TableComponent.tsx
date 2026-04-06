import React, { useEffect, useState, useRef } from 'react';
import { TableBody } from './body/TableBody';

interface Props {
  datas?: any;
  variants?: any;
  isEdit: boolean;
  rowEnter?: (id: number) => void;
  setIsEdit: React.Dispatch<React.SetStateAction<boolean>>;
  tableHead: string[];
  aliases?: { [key: string]: string };
  onDelete?: (id: number) => Promise<void>;
  onCellChange: (id: number, field: string, value: string) => void;
  onSelectChange?: (id: any, field: any, value: any) => void;
}

const TableComponent: React.FC<Props> = ({ ...props }) => {
  const { datas, isEdit, setIsEdit, tableHead, aliases, onDelete, onCellChange, onSelectChange, rowEnter } = props;
  const [focusedCell, setFocusedCell] = useState<number | null>(0);
  const tableBodyRef = useRef<HTMLTableSectionElement | null>(null);
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);

  const handleKeyDown = (event: KeyboardEvent) => {
    if (!isEdit) return;

    switch (event.key) {
      case 'ArrowDown':
        event.preventDefault();
        setFocusedCell((prev) => {
          const newIndex = Math.min((prev ?? 0) + 1, (datas?.length || 0) - 1);
          scrollToCell(newIndex);
          return newIndex;
        });
        break;

      case 'ArrowUp':
        event.preventDefault();
        setFocusedCell((prev) => {
          const newIndex = Math.max((prev ?? 0) - 1, 0);
          if (newIndex === 0) {
            if (scrollContainerRef.current) {
              scrollContainerRef.current.scrollTo({ top: 0, behavior: 'smooth' });
            }
          } else {
            scrollToCell(newIndex);
          }
          return newIndex;
        });
        break;

      case 'Escape':
        event.preventDefault();
        setFocusedCell(null);
        setIsEdit(false);
        if (scrollContainerRef.current)
          scrollContainerRef.current.scrollTo({ top: 0, behavior: 'smooth' });
        break;

      case 'Delete':
        event.preventDefault();
        setFocusedCell((prev) => {
          if (prev) {
            onDelete && onDelete(datas[prev].id);
            return prev - 1;
          } else {
            onDelete && onDelete(datas[0].id);
            return prev;
          }
        });
        break;

      default:
        break;
    }
  };

  const scrollToCell = (index: number) => {
    if (tableBodyRef.current) {
      const cell = tableBodyRef.current.children[index];
      if (cell) {
        cell.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
      }
    }
  };

  useEffect(() => {
    window.addEventListener('keydown', handleKeyDown);
    isEdit ? setFocusedCell(0) : setFocusedCell(null);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isEdit]);

  return (
    <div ref={scrollContainerRef} className="w-full overflow-auto max-h-[40vh] font-semibold text-sm">
      <table className="w-full min-w-max table-auto shadow-md border-2">
        <thead className='sticky top-[-1px]'>
          <tr>
            {tableHead.map((head) => (
              <th key={head} className="border-b  p-4 bg-blue-400 text-white font-medium">
                {aliases?.[head] || head}
              </th>
            ))}
            {isEdit && rowEnter == null && (
              <th className="border-b  p-4 bg-blue-400 text-white font-medium">Aksi</th>
            )}
          </tr>
        </thead>
        <TableBody
          onDelete={onDelete}
          fields={tableHead}
          isEdit={isEdit}
          initialDatas={datas}
          focusedCell={focusedCell}
          onCellChange={onCellChange}
          onSelectChange={onSelectChange}
          ref={tableBodyRef}
          setFocusedCell={setFocusedCell}
          rowEnter={rowEnter}
        />
      </table>
    </div>
  );
};

export { TableComponent };