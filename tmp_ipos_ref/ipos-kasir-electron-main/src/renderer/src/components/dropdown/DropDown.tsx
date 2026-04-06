import React, { useRef, useEffect } from 'react';

interface DropdownProps {
    items: any[];
    onSelect: (item: any) => void;
    isVisible: boolean;
    highlightedIndex: number;
    isCode?: boolean
}

const Dropdown: React.FC<DropdownProps> = ({ items, onSelect, isVisible, highlightedIndex, isCode = true }) => {
    const itemRefs = useRef<(HTMLDivElement | null)[]>([]);
    const scrollContainerRef = useRef<HTMLDivElement | null>(null);

    useEffect(() => {
        if (highlightedIndex > 0 && itemRefs.current[highlightedIndex]) {
            itemRefs.current[highlightedIndex]?.scrollIntoView({
                behavior: 'smooth',
                block: 'nearest',
            });
        } else if (highlightedIndex == 0 && itemRefs.current[highlightedIndex]) {
            if (scrollContainerRef.current) {
                scrollContainerRef.current.scrollTo({ top: 0, behavior: 'smooth' });
            }
        }
    }, [highlightedIndex]);

    if (!isVisible) return null;

    return (
        <div ref={scrollContainerRef} className="absolute shadow-2xl bg-white border-4 border-black max-h-[30vh] overflow-auto w-1/3 z-[99]">
            {items.length === 0 ? (
                <div className="py-2 px-4 text-center ">Barang tidak ditemukan</div>
            ) : (
                <div className="">
                    <div className="flex items-center justify-between py-2 px-4 border-b gap-x-12">
                        {isCode &&
                            <div className="font-semibold w-1/2">Kode</div>
                        }
                        <div className="font-semibold w-1/2">Nama </div>
                    </div>
                    {items.map((item, index) => (
                        <div
                            key={index}
                            ref={(el) => (itemRefs.current[index] = el)}
                            className={`flex items-center gap-x-12 border-b py-2 px-4 cursor-pointer hover:bg-blue-100 font-bold ${highlightedIndex === index ? 'bg-blue-100' : ''}`}
                            onClick={() => onSelect(item)}
                        >
                            {isCode && <div className="w-1/2 ">{item.barcode}</div>}
                            <div className="text-start w-1/2 ">{item.name}</div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
};

export default Dropdown;