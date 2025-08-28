import { type FC } from "react";
import { useContext, useEffect, useState } from "react";
import { LanguageContext } from "../../../contexts/LanguageContext";
import { calc_target_from_array } from "../../../utils/calculator";
import { TargetSlice } from "../../../types/auth";
import useRequest from "../../../hooks/calls";
import { TRANSLATIONS } from "../../../utils/constants";

interface TargetFieldProps {
    uuid: string;
    title:string;
    params?: object;
    register: any;
    coinChange?: {
        egp_to_sar: number,
        date: string,
    };
    setValue: any;
    count_name: string;
    value_name: string;

}

const TargetField: FC<TargetFieldProps> = ({ uuid , title, register , setValue , value_name , count_name , coinChange = { egp_to_sar: 1, date: "" }, params = {} }) => {
    const { data, loading } = useRequest<TargetSlice>({
        url:"api/commission/targets",
        params: { user_uuid: uuid, ...params },
    }, [])
    return (
        (data?.results?.length || -1) > 0 ? (
        <>
            <label
                className="col-span-1 place-self-center"
                htmlFor="target_Team"
            >
                {title}
            </label>
            <div className="col-span-2 place-self-center flex flex-row justify-center items-center gap-3">
                <input
                    className="col-span-2 place-self-center w-[20%] outline-none px-1 text-center rounded-lg border border-btns-colors-primary  bg-light-colors-login-third-bg dark:bg-dark-colors-login-third-bg"
                    type="number"
                    {...register(count_name, { valueAsNumber: true, min: { value: 0, message: "min value is 0" } })}
                    onChange={(e) => {
                        setValue(count_name,parseInt(e.target.value));
                        setValue(value_name,calc_target_from_array(parseInt(e.target.value), data?.results || []) * coinChange.egp_to_sar);
                    }}
                />
                <input
                    className="border-none text-center w-[47%] col-span-2 place-self-center outline-none px-4 rounded-lg border border-btns-colors-primary  bg-light-colors-login-third-bg dark:bg-dark-colors-login-third-bg"
                    {...register(value_name, { 
                        valueAsNumber: true, 
                        min: { value: 0, message: "min value is 0" },
                    })}
                    disabled
                />
            </div>
        </>
        ) : null )
}

export default TargetField
