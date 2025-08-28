import { useContext, useEffect, useState, type FC } from "react";
import Container from "../../layouts/Container/Container";
import { BasicDetails, Subscription } from "../../types/auth";
import LoadingComponent from "../LoadingComponent/LoadingComponent";
import { TotalLeads } from "../TotalLeadsCard/TotalLeadsCard";
import { sendRequest } from "../../calls/base";
import Swal from "sweetalert2";
import { SalaryType } from "../../pages/Salary/Salary";
import { useNavigate } from "react-router-dom";
import { LanguageContext } from "../../contexts/LanguageContext";
import { TRANSLATIONS } from "../../utils/constants";
import { useAuth } from "../../hooks/auth";
import { checkPermission } from "../../utils/permissions/permissions";
import { useForm } from "react-hook-form";
import TargetField from "./TargetField/TargetField";

interface SalaryFormProps extends React.HTMLProps<HTMLDivElement> {
    oldSalary?: SalaryType;
    basic: BasicDetails;
    user_uuid: string;
    date: Date;
    subscriptions?: Subscription[] | null;
    american?: Subscription[] | null;
    department?: string;
    analytics?: TotalLeads;
    coinChange?: {
        egp_to_sar: number,
        date: string,
    }

}
const SalaryForm: FC<SalaryFormProps> = ({
    className,
    oldSalary,
    basic,
    analytics,
    date,
    subscriptions,
    american,
    department,
    user_uuid,
    coinChange,
}) => {
    const {lang} = useContext(LanguageContext)
    const {auth} = useAuth()
    const [loading, setLoading] = useState(false);
    const navigate = useNavigate();    
    const { register, handleSubmit, watch, setValue, getValues } = useForm<SalaryType>({
        defaultValues: oldSalary
            ? oldSalary
            : {
                  uuid: '',
                  user:user_uuid,
                  basic:basic.uuid,
                  target: 0,
                  target_count: 0,
                  target_Team: 0,
                  target_Team_count: 0,
                  plus: 0,
                  plus_count: 0,
                  plus_10:0,
                  plus_10_count: 0,
                  american: 0,
                  american_count: 0,
                  deduction: 0,
                  gift: 0,
                  subscriptions: 0,
                  subscriptions_count: 0,
                  project: basic.project,
                  american_subscriptions: 0,
                  american_subscriptions_count: 0,
                  ...{ salary: basic ? parseInt(`${basic.basic}`) : 0 },
              }
    });
    const onSubmit = (data: SalaryType) => {
        setLoading(true);
        const form = new FormData();
        Object.entries(data).forEach(([key, value]) => {
            if ((key === "user" || key === "basic") && oldSalary){
                form.append(key, String(value.uuid));
            }
            else {
                form.append(key, String(value));
            }
        });
        console.log(form);
        console.log(data);
        if (!oldSalary) {
            form.append(
                "date",
                `${date.getFullYear()}-${
                    date.getMonth() + 1
                }-${date.getDate()}`
            );
        }
        sendRequest({
            url: "api/commission/salary",
            method: oldSalary ? "PUT" : "POST",
            data: form,
            params: oldSalary
                ? { uuid: oldSalary.uuid }
                : undefined,
        })
            .then((data) => {
                Swal.fire({
                    position: "center",
                    icon: "success",
                    title: "Successfully Gived",
                    showConfirmButton: false,
                    timer: 1000,
                }).then(() => {
                    navigate(-1);
                });
            })
            .catch((error) => {
                Swal.fire({
                    position: "center",
                    icon: "error",
                    title: "Faild to Give",
                    showConfirmButton: false,
                    timer: 1000,
                });
            })
            .finally(() => setLoading(false));
}
    const target = watch("target");
    const target_Team = watch("target_Team");
    const plus = watch("plus");
    const plus_10 = watch("plus_10");
    const american_ = watch("american");
    const subscriptions_ = watch("subscriptions");
    const american_subscriptions = watch("american_subscriptions");
    const gift = watch("gift");
    const subscriptions_count = watch("subscriptions_count")
    const american_subscriptions_count = watch("american_subscriptions_count")
    const deduction = watch("deduction");
    const american_count = watch("american_count")

    useEffect(() => {
        const baseSalary = basic ? parseInt(`${basic.basic}`) : 0;
        const total =
            baseSalary +
            target +
            target_Team +
            plus +
            plus_10 +
            american_ +
            subscriptions_ +
            american_subscriptions +
            gift -
            deduction;

        setValue("salary", Math.round(total));
    }, [
        target,
        target_Team,
        plus,
        plus_10,
        american_,
        subscriptions_,
        american_subscriptions,
        gift,
        deduction,
        basic,
        setValue,
    ]);
    useEffect(()=>{
        const subscriptionValue = getSubscriptionValue((subscriptions_count || 0),subscriptions || [])
        setValue("subscriptions",subscriptionValue)
    },[subscriptions_count])
    useEffect(()=>{
        const subscriptionValue = getSubscriptionValue((american_subscriptions_count || 0),american || [])
        setValue("american_subscriptions",subscriptionValue)
    },[american_subscriptions_count])
    useEffect(()=>{
        setValue("american",(american_count || 0) * (analytics?.american_leads_price || 1))
    },[american_count])
    const getSubscriptionValue = (count: number, subs: Subscription[]) => {
        for (let index = 0; index < subs.length; index++) {
            const element = subs[index];
            if (element.count === count) {
                return element.value;
            }
        }
        return 0;
    };
    const handleDelete = (e:React.MouseEvent<HTMLButtonElement>)=>{
        e.preventDefault();
        Swal.fire({
            title: "Are you sure?",
            text: "You won't be able to revert this!",
            icon: "warning",
            showCancelButton: true,
            confirmButtonColor: "#3085d6",
            cancelButtonColor: "#d33",
            confirmButtonText: "Yes, delete it!",
        }).then((result) => {
            if (result.isConfirmed) {
                setLoading(true);
                sendRequest({
                    url: `api/commission/salary`,
                    method: "DELETE",
                    params: { uuid : getValues("uuid") },
                })
                   .then(() => {
                        Swal.fire(
                            "Deleted!",
                            "Salary record has been deleted.",
                            "success"
                        ).then(() => {
                            navigate(-1);
                        });
                    })
                   .catch((error) => {
                        console.error(error);
                        Swal.fire("Error!", error.message, "error")})}})
    }
    return (
        <Container className={`${className} relative w-[500px] h-fit`}>
            {loading ? <LoadingComponent /> : <></>}
            <h1 className="text-2xl text-btns-colors-primary text-center w-full">
                Salary
            </h1>

            <form
                className="grid grid-cols-3 gap-1 my-2 overflow-x-hidden text-[0.95rem]"
                onSubmit={handleSubmit(onSubmit)}
            >
                <input
                    className="hidden"
                    {...register("basic")}
                />
                <input 
                    className="hidden"
                    {...register("user" )}
                />

                <TargetField 
                    uuid={user_uuid}
                    register={register}
                    coinChange={coinChange}
                    setValue={setValue}
                    count_name="target_count"
                    value_name="target"
                    title={TRANSLATIONS.Salary.form.target[lang]}
                />
                <TargetField 
                    uuid={user_uuid}
                    register={register}
                    coinChange={coinChange}
                    params={{table_type:"team"}}
                    setValue={setValue}
                    count_name="target_Team_count"
                    value_name="target_Team"
                    title={TRANSLATIONS.Salary.form.targetteam[lang]}
                />
                {department === "marketing" ? (
                    <>
                        <label
                            className="col-span-1 place-self-center"
                            htmlFor="plus"
                        >
                            {TRANSLATIONS.Salary.form.plus[lang]}{" "}
                        </label>
                        <div className="col-span-2 place-self-center flex flex-row justify-center items-center gap-3">
                            <input
                                className="col-span-2 place-self-center w-[20%] outline-none px-1 text-center rounded-lg border border-btns-colors-primary  bg-light-colors-login-third-bg dark:bg-dark-colors-login-third-bg"
                                type="number"
                                {...register("plus_count", { valueAsNumber: true, min: { value: 0, message: "min value is 0" } })}                                
                                onChange={(e) => {
                                    setValue("plus_count",parseInt(e.target.value));
                                    setValue("plus", (parseInt(e.target.value) * (analytics?.plus_price || 1)) || 0);
                                }} 
                            />                        
                            <input
                                className="border-none text-center w-[47%] col-span-2 place-self-center outline-none px-4 rounded-lg border border-btns-colors-primary  bg-light-colors-login-third-bg dark:bg-dark-colors-login-third-bg"
                                {...register("plus",{
                                    valueAsNumber:true , 
                                    min:{value:0,message:"min value is 0"},
                                })}  
                                disabled
                            />
                        </div>
                        <label
                            className="col-span-1 place-self-center"
                            htmlFor="plus_10"
                        >
                            {TRANSLATIONS.Salary.form.plus_10[lang]}{" "}
                        </label>
                        <div className="col-span-2 place-self-center flex flex-row justify-center items-center gap-3">
                            <input
                                className="col-span-2 place-self-center w-[20%] outline-none px-1 text-center rounded-lg border border-btns-colors-primary  bg-light-colors-login-third-bg dark:bg-dark-colors-login-third-bg"
                                type="number"
                                {...register("plus_10_count", { valueAsNumber: true, min: { value: 0, message: "min value is 0" } })}                                
                                onChange={(e) => {
                                    setValue("plus_10_count",parseInt(e.target.value));
                                    setValue("plus_10", (parseInt(e.target.value) * (analytics?.plus_10_price || 1)) || 0);
                                }} 
                            />                        
                            <input
                                className="border-none text-center w-[47%] col-span-2 place-self-center outline-none px-4 rounded-lg border border-btns-colors-primary  bg-light-colors-login-third-bg dark:bg-dark-colors-login-third-bg"
                                {...register("plus_10",{
                                    valueAsNumber:true , 
                                    min:{value:0,message:"min value is 0"},
                                })}  
                                disabled
                            />
                        </div>
                        <label
                            className="col-span-1 place-self-center"
                            htmlFor="american"
                        >
                            {TRANSLATIONS.Salary.form.american[lang]}
                        </label>
                        <div className="col-span-2 place-self-center flex flex-row justify-center items-center gap-3">
                            <input
                                {...register("american_count",{valueAsNumber:true})}  
                                className="col-span-2 place-self-center w-[20%] outline-none px-1 text-center rounded-lg border border-btns-colors-primary  bg-light-colors-login-third-bg dark:bg-dark-colors-login-third-bg"
                            />
                            <input
                                {...register("american",{
                                    valueAsNumber:true,
                                })}
                                disabled
                                className="border-none text-center w-[47%] col-span-2 place-self-center outline-none px-4 rounded-lg border border-btns-colors-primary  bg-light-colors-login-third-bg dark:bg-dark-colors-login-third-bg"
                            />
                        </div>

                        <label
                            className="col-span-1 place-self-center"
                            htmlFor="subscriptions"
                        >
                            {TRANSLATIONS.Salary.form.subscription[lang]}
                        </label>
                        <div className="col-span-2 place-self-center flex flex-row justify-center items-center gap-3">
                            <input
                                {...register("subscriptions_count",{valueAsNumber:true })}
                                className="col-span-2 place-self-center w-[20%] outline-none px-1 text-center rounded-lg border border-btns-colors-primary  bg-light-colors-login-third-bg dark:bg-dark-colors-login-third-bg"
                            />
                            <input
                                {...register("subscriptions",{valueAsNumber:true })}
                                disabled
                                className="border-none text-center w-[47%] col-span-2 place-self-center outline-none px-4 rounded-lg border border-btns-colors-primary  bg-light-colors-login-third-bg dark:bg-dark-colors-login-third-bg"
                            />
                        </div>

                        <label
                            className="col-span-1 place-self-center"
                            htmlFor="american_subscriptions"
                        >
                            {TRANSLATIONS.Salary.form.americanSubscription[lang]}
                        </label>
                        <div className="col-span-2 place-self-center flex flex-row justify-center items-center gap-3">
                            <input
                                {...register("american_subscriptions_count",{valueAsNumber:true})}
                                className="col-span-2 place-self-center w-[20%] outline-none px-1 text-center rounded-lg border border-btns-colors-primary  bg-light-colors-login-third-bg dark:bg-dark-colors-login-third-bg"
                            />
                            <input
                                {...register("american_subscriptions",{valueAsNumber:true})}
                                disabled
                                className="border-none text-center w-[47%] col-span-2 place-self-center outline-none px-4 rounded-lg border border-btns-colors-primary  bg-light-colors-login-third-bg dark:bg-dark-colors-login-third-bg"
                            />
                        </div>
                    </>
                ) : null}
                {department === "sales" ? (
                    <>
                        <label
                            className="col-span-1 place-self-center"
                            htmlFor="american_subscriptions"
                        >
                            {TRANSLATIONS.Salary.form.americanSubscription[lang]}
                        </label>
                        <input
                            {...register("american_subscriptions",{valueAsNumber:true })}
                            className="w-5/6 col-span-2 place-self-center outline-none px-4 rounded-lg border border-btns-colors-primary  bg-light-colors-login-third-bg dark:bg-dark-colors-login-third-bg"
                        />
                    </>
                ) : null}

                <section className="col-span-full place-self-center grid grid-cols-3 gap-1 border p-2 mt-2 rounded-xl dark:border-[lightgray] border-[darkgray]">
                    <label
                        className="col-span-1 place-self-center"
                        htmlFor="deduction"
                    >
                        {TRANSLATIONS.Salary.form.deduction[lang]}
                    </label>
                    <input
                        {...register("deduction",{valueAsNumber:true})}
                        className="w-5/6 col-span-2 place-self-center outline-none px-4 rounded-lg border border-btns-colors-secondry  bg-light-colors-login-third-bg dark:bg-dark-colors-login-third-bg"
                    />
                    <label
                        className="col-span-1 place-self-center"
                        htmlFor="gift"
                    >
                        {TRANSLATIONS.Salary.form.gift[lang]}
                    </label>
                    <input
                        {...register("gift",{valueAsNumber:true})}
                        className="w-5/6 col-span-2 place-self-center outline-none px-4 rounded-lg border border-btns-colors-primary  bg-light-colors-login-third-bg dark:bg-dark-colors-login-third-bg"
                    />
                </section>

                <label
                    className="col-span-1 place-self-center text-2xl"
                    htmlFor="salary"
                >
                    {TRANSLATIONS.Salary.form.title[lang]} (EGP)
                </label>
                <input
                    {...register("salary",{valueAsNumber:true})}
                    disabled
                    className="hidden"
                />
                <label className="bg-[transparent] w-full col-span-2 place-self-center text-3xl outline-none border-none text-center">{watch("salary")}</label>

                {
                oldSalary ? (
                    <div className="col-span-full flex flex-row-reverse gap-5">
                        {
                            checkPermission(auth,"change_commission")?
                            <button
                                type="submit"
                                className="col-span- h-10 bg-btns-colors-primary rounded-lg w-2/3 place-self-center my-2"
                            >
                                {TRANSLATIONS.Salary.form.update[lang]}
                            </button>
                            :null
                        }
                        {
                            checkPermission(auth,"delete_commission")?
                            <button
                                onClick={handleDelete}
                                className="col-span-full h-10 bg-btns-colors-secondry rounded-lg w-2/3 place-self-center my-2"
                            >
                                {TRANSLATIONS.Delete[lang]}
                            </button>
                            :null
                        }
                    </div>
                ) : (
                    <button
                        type="submit"
                        className="col-span-full h-10 bg-btns-colors-primary rounded-lg w-2/3 place-self-center my-2"
                    >
                        {TRANSLATIONS.Salary.form.give[lang]}
                    </button>
                )
                }
            </form>
        </Container>
    );
};

export default SalaryForm;
