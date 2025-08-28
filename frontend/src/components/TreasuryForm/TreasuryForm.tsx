import React, { SetStateAction, useContext, useRef, useState, type EventHandler, type FC, type FormEventHandler } from 'react';
import Container from '../../layouts/Container/Container';
// import SelectComponent from '../SelectComponent/SelectComponent';
import { DEFAULT_INPUT_STYLE } from '../../utils/styles';
import { sendRequest } from '../../calls/base';
import { parseFormData } from '../../utils/converter';
import LoadingComponent from '../LoadingComponent/LoadingComponent';
import Swal from 'sweetalert2';
import { TRANSLATIONS } from '../../utils/constants';
import { LanguageContext } from '../../contexts/LanguageContext';
// import SelectComponent from '../SelectComponent/SelectComponent';

interface TreasuryFormProps {
    creator_uuid: string;
    url: string;
    color: string;
    header: string;
    setRefresh:React.Dispatch<SetStateAction<boolean>>;
    group?:boolean
}



const TreasuryForm: FC<TreasuryFormProps> = ({creator_uuid,url , color , header , setRefresh,group=false}) => {
    const {lang} = useContext(LanguageContext)
    const [loading,setLoading] = useState<boolean>(false)
    const formRef = useRef<HTMLFormElement>(null);
    const onSubmit:FormEventHandler<HTMLFormElement> = (e) => {
        const form_data = parseFormData(e)
        const project_type = form_data.get("group")
        if (project_type?.toString()==="*"){
            form_data.delete("group")
        }
        
        e.preventDefault();
        setLoading(true)
        sendRequest({
            url: url,
            method: 'POST',
            data: form_data
        }).then(data=>{
            Swal.fire({
                position: "center",
                icon: "success",
                title: "Successfully",
                showConfirmButton: false,
                timer: 1000
              })
            setRefresh(prev=>!prev)
            if (formRef.current){
                formRef.current.reset();
                (formRef.current.elements[1] as HTMLTextAreaElement)?.focus()
            }
        }).catch(
            error => Swal.fire({
                title: 'Auto close alert!',
                text: error.message,
                timer: 2000
              })
        ).finally(() => {
            setLoading(false);

        })
    }
    return (
    <Container className='relative w-full md:w-2/3 h-fit flex flex-col justify-start'>
        {
            loading? <LoadingComponent/> : <></>
        }
        <span className={`text-2xl w-full text-center text-${color}`}>{header}</span>
        <form ref={formRef} action="" method="post" className='grid grid-cols-5 space-y-4 mb-4' onSubmit={onSubmit}>
            <input type="hidden" name="creator" value={creator_uuid} readOnly/>

            <label className='col-span-1 place-self-center' htmlFor="details">{TRANSLATIONS.Treasury.inform.details[lang]}</label>
            <textarea className={`col-span-4 ${DEFAULT_INPUT_STYLE}`} name="details" id="details" minLength={3} required/>
            {/* {
                group ?
                <SelectComponent 
                    url='api/treasury/projects-group'
                    LabelName={TRANSLATIONS.UsersList.filters.group[lang]}
                    LabelClassName='col-span-1 place-self-center'
                    selectClassName={`col-span-4 w-2/3`}
                    config={{label: 'name' , value: 'uuid'}}
                    name='group'
                    moreOptions={[{label:"-",value:"*"}]}
                    />
                : null

            } */}

            <label className= 'col-span-1 place-self-center' htmlFor="amount">{TRANSLATIONS.Treasury.inform.amount[lang]}</label>
            <input className={`col-span-2 ${DEFAULT_INPUT_STYLE}`} inputMode='numeric' min={10} type="number" name="amount" id="amount" required/>

            <button type='submit' className={`bg-${color} rounded-xl w-3/6 h-9 justify-self-center col-span-5 font-bold`}>{TRANSLATIONS.Treasury.inform.submit[lang]}</button>

        </form>
    </Container>
    );
}

export default TreasuryForm;
