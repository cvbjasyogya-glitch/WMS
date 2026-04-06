import React, { forwardRef } from 'react';
import { FaSearch } from 'react-icons/fa';
import { InputText } from '../input/InputText';

interface SearchInputProps {
    placeholder?: string;
    label?: string;
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
    onKeyDown: (event: React.KeyboardEvent) => void;
    className?: string;
}

const SearchInput = forwardRef<HTMLInputElement, SearchInputProps>(
    ({ placeholder = "Masukkan kode atau nama barang", label = "input", onChange, onKeyDown, className = "" }, ref) => (
        <div className={`flex items-center gap-x-4 ${className}`}>
            <InputText
                placeholder={placeholder}
                name="input"
                label={label}
                type="text"
                outline="box"
                icon={<FaSearch />}
                ref={ref}
                className="w-full rounded-md py-2 bg-blue-100/50"
                onChange={onChange}
                onKeyDown={onKeyDown}
            />
            <div className="italic text-gray-500">{'(ctrl+f)'}</div>
        </div>
    )
);

export default SearchInput;