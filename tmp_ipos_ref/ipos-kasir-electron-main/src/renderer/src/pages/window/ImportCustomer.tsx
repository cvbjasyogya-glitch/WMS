import React, { useState } from 'react';
import { useDropzone } from 'react-dropzone';
import * as XLSX from 'xlsx';
import { MasterLayout } from '../../layout/MasterLayout';
import MainLayout from '../../layout/MainLayout';
import { FaCheck, FaUpload } from 'react-icons/fa';
import { FaSpinner } from 'react-icons/fa';
import { Button } from '../../components/button/Button';
import { useNavigate } from 'react-router-dom';

interface Props { }

const ImportCustomer: React.FC<Props> = () => {
    const [loading, setLoading] = useState(false);
    const [progress, setProgress] = useState(0);
    const [completed, setCompleted] = useState(false);
    const navigate = useNavigate()
    const handleUpload = async (payload: any, section: string) => {
        const response = await (window as any).api[section].postMany(payload);
        if (response.success) console.log(section + ' Uploaded!')
        else console.error(response.error);
    }

    const customerProcess = async (workbook: XLSX.WorkBook): Promise<any> => {
        const data = workbook.Sheets['customer'];
        if (!data) {
            console.error('Sheet "customer" tidak ditemukan');
            return { datas: [], kategoriMap: {} };
        }
        const datas = XLSX.utils.sheet_to_json<any>(data);

        return { datas }
    };



    const onDrop = (acceptedFiles: File[]) => {
        const file = acceptedFiles[0];
        const reader = new FileReader();

        setLoading(true);
        setProgress(0);

        reader.onload = async (event) => {
            try {
                const data = new Uint8Array(event.target?.result as ArrayBuffer);
                const workbook = XLSX.read(data, { type: 'array' });
                const { datas: customerData } = await customerProcess(workbook)
                setProgress(20);
                console.log(customerData)
                await handleUpload(customerData, 'customer');
                setProgress(100);
            } catch (error) {
                console.error('Error processing file:', error);
            } finally {
                setCompleted(true);
            }
        };

        reader.readAsArrayBuffer(file);
    };

    const { getRootProps, getInputProps, isDragActive } = useDropzone({
        onDrop,
        accept: {
            'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
            'application/vnd.ms-excel': ['.xls'],
        },
    });

    return (
        <MainLayout>
            <div className="bg-slate-100 min-h-screen">
                <MasterLayout title="Import Pembeli" desc="Anda dapat menambahkan data pembeli">
                    <div className="p-8 bg-slate-50 border">
                        <div className="py-4">
                            {loading ? (
                                <div className="flex flex-col items-center">
                                    {completed ?
                                        <div className='flex flex-col items-center'>
                                            <FaCheck className=" text-green-500 text-4xl mb-4" />
                                            <p className="text-lg text-gray-600">File berhasil diproses</p>
                                        </div>
                                        : <div>
                                            <FaSpinner className="animate-spin text-blue-500 text-4xl mb-4" />
                                            <p className="text-lg text-gray-600">Memproses file, mohon tunggu...</p>
                                        </div>}
                                    <div className="w-full bg-gray-200 rounded-full h-4 mt-4">
                                        <div
                                            className="bg-blue-500 h-4 rounded-full "
                                            style={{ width: `${progress}%` }}
                                        />
                                    </div>
                                    <p className="mt-2 font-bold text-gray-600 text-xl">{progress}%</p>
                                    {completed && <Button label="Kembali" className="mt-2" onClick={() => navigate(-1)} />}
                                </div>
                            ) : (
                                <div
                                    {...getRootProps()}
                                    className={`border-2 border-dashed rounded p-4 text-center cursor-pointer ${isDragActive ? 'border-blue-400' : 'border-gray-300'
                                        }`}
                                >
                                    <div className="q-full flex justify-center mb-4">
                                        <FaUpload size={48} className="text-gray-400" />
                                    </div>
                                    <input {...getInputProps()} />
                                    {isDragActive ? (
                                        <p className="text-lg">Drop file Anda di sini...</p>
                                    ) : (
                                        <p className="text-lg">
                                            Tarik dan jatuhkan file Excel Anda di sini, atau klik untuk mengunggah.
                                        </p>
                                    )}
                                </div>
                            )}
                        </div>
                    </div>
                </MasterLayout>
            </div>
        </MainLayout>
    );
};

export { ImportCustomer };