 *INSTRUCTION*
Now i want to create scenario with apiKey enabling smartBooking and add smartBook group. for this 
Provid option in the UI to create apiKEy with sbEnabled  or not
If enabled then the apiKey should be created with sb.
ANd before enabking SB first the SB group should be created then the created sb group should be added to the apiKey creation.
To created SB group int the Supplier UI we need to give option that this supplier belong to APikey or SbGroup or Both.
IF APikey then the created contract for that supplier should be added only to the APikey
IF  SbGroup then the created contract for that supplier should be added only to the SbGroup
If Both then the created contract for that supplier should be added to both ApikEY and SbGroup.
By Default it should be APikey
THe exiting flow should not change. THis modification should reflect in Create Scenario screen and from Custom templates selting the template

*SampleCurls*

Curl: Create Curl
curl --location 'https://enigma-portal-staging.almosafer.com/api/dynamic-forms/smart_booking_group' \
--header 'accept: application/json, text/javascript' \
--header 'accept-language: en-US,en;q=0.9' \
--header 'authorization: Bearer eyJraWQiOiJqd3Qta2V5LWlkIiwidHlwIjoiSldUIiwiYWxnIjoiUlMyNTYifQ.eyJhdWQiOiJsb29rdXBfYWRtaW5fYXBpIiwidXNlcl9uYW1lIjoic2FrdGhpdmVsLnN1bmRlckBhbG1vc2FmZXIuY29tIiwic2NvcGUiOlsicmVhZCIsIndyaXRlIl0sImV4cCI6MTc4NTc1NDEwOCwiaWF0IjoxNzg1NjY3NzA4LCJqdGkiOiJleUowZVhBaU9pSktWMVFpTENKaGJHY2lPaUpTVXpJMU5pSjkuZXlKaGRXUWlPaUpzYjI5cmRYQmZZV1J0YVc1ZllYQnBJaXdpWlhod0lqb3hOemcxTnpVME1UQTRMQ0oxYzJWeVgyNWhiV1VpT2lKellXdDBhR2wyWld3dWMzVnVaR1Z5UUdGc2JXOXpZV1psY2k1amIyMGlMQ0pqYkdsbGJuUmZhV1FpT2lKaVlXTnJiMlptYVdObFgyeHZiMnQxY0Y5M2NtbDBaU0lzSW1wMGFTSTZJamhqWTJVM05ESmhMVGcwTXpZdE5EWTBaQzA1TWpobUxUQm1OemRtT0RNMlpUUXdaaUlzSW5OamIzQmxJanBiSW5KbFlXUWlMQ0ozY21sMFpTSmRmUS5xU0xwNmFyU2VkT1lNbWFHWk03Zzd1UW4tdW9pU1VOWnF0VjZ0Z2dOb1drTjVUMFV6alA1dE5Pc1o2ODZaYmxmMFd3djZwT2VyaVZ4eVZ0dldFX3ROdU1obEFZWmNYYmJyallmd21vR0toS0RPQm5hWnl4c0VUb0kyUGlBSlJjSHVSYzhYQ1ZKUjM3d0ExMjBPQjQ0UG81bmJremJ5RE5lZF9ZMkhVa0FPTjlzU29WYjdTQ0FzRnRxV0RwX21SZDhyUWsxN0k0S3VELUxqVVNsdHcySi1fQjFLSzlFLUFhX183Xy1vQjRFNXZ5TTBpc0pBWnJTQkZUNU5TdXZiaTRpckkxNjFjS3RYOEE4dXhFbEZRVXJ5MUJyMlN1alZzWWtwTllhNG1uNzJmaS1adExYS2J6bEtpVnlFRzd0MXlINWpnZ3VNdk5ndHhaM0VMcDliOWREUmciLCJjbGllbnRfaWQiOiJiYWNrb2ZmaWNlX2xvb2t1cF93cml0ZSJ9.H2dSRsGa8Kn51MooA_WkzjtZHgZzEzB7uvjzggMYtmuVv-mMyP8p-f3lFm_I8Js6Wxf3kS6aR_qjsR-xASxryDj9QLYcP9TPH1KowzTmvL-E7d2YYHwAefhMetOHY341j7wLXGxWRBdKQnh1-b71rKV27YSJINO87_i29Z-0mzGsedS8LcYkdrviA3JkjHxHg2SCf9Si1CLGznDVreQXEnCEr2iERVwX2OmHYPY5BxK4WntQu-TmdhWyckHVI2o8qgtN5HrQe1ar8lVuhkXn1rWMVdb-EpVyls_Az8BZ89tK85uEJpZHRnbd-muceYBa0d3o8R2jPpJ1YGGkIVUksg' \
--header 'content-type: application/json' \
--header 'x-tenant: 6180e4de152d227b72261039' \
--data '{"name":"sampleNew","isActive":true,"contracts":["6a6f209d740731730e3b3350"],"submit":true}'

Resposne:
{
    "_id": "6a6f79fce6d0496d47421c02",
    "name": "sampleNew",
    "isActive": true,
    "contracts": [
        "6a6f209d740731730e3b3350"
    ],
    "submit": true,
    "created_at": 1785690620109,
    "update_at": 1785690620109,
    "userDetail": {
        "userId": 41,
        "firstName": "sakthivel",
        "lastName": "sunder",
        "email": "sakthivel.sunder@almosafer.com",
        "userName": "sakthivel.sunder@almosafer.com",
        "createdBy": 23,
        "updatedBy": 52,
        "userAdditionalData": null,
        "blocked": false,
        "ssoUser": false,
        "countryCode": null,
        "phoneNumber": null,
        "isAdmin": false
    },
    "createdBy": "41",
    "autoId": 336
}

Curl: Get Sb Group
curl --location 'https://enigma-portal-staging.almosafer.com/api/dynamic-forms/smart_booking_group/6a6f796fe6d0496d47421c01' \
--header 'accept: application/json, text/javascript' \
--header 'accept-language: en-US,en;q=0.9' \
--header 'authorization: Bearer eyJraWQiOiJqd3Qta2V5LWlkIiwidHlwIjoiSldUIiwiYWxnIjoiUlMyNTYifQ.eyJhdWQiOiJsb29rdXBfYWRtaW5fYXBpIiwidXNlcl9uYW1lIjoic2FrdGhpdmVsLnN1bmRlckBhbG1vc2FmZXIuY29tIiwic2NvcGUiOlsicmVhZCIsIndyaXRlIl0sImV4cCI6MTc4NTc1NDEwOCwiaWF0IjoxNzg1NjY3NzA4LCJqdGkiOiJleUowZVhBaU9pSktWMVFpTENKaGJHY2lPaUpTVXpJMU5pSjkuZXlKaGRXUWlPaUpzYjI5cmRYQmZZV1J0YVc1ZllYQnBJaXdpWlhod0lqb3hOemcxTnpVME1UQTRMQ0oxYzJWeVgyNWhiV1VpT2lKellXdDBhR2wyWld3dWMzVnVaR1Z5UUdGc2JXOXpZV1psY2k1amIyMGlMQ0pqYkdsbGJuUmZhV1FpT2lKaVlXTnJiMlptYVdObFgyeHZiMnQxY0Y5M2NtbDBaU0lzSW1wMGFTSTZJamhqWTJVM05ESmhMVGcwTXpZdE5EWTBaQzA1TWpobUxUQm1OemRtT0RNMlpUUXdaaUlzSW5OamIzQmxJanBiSW5KbFlXUWlMQ0ozY21sMFpTSmRmUS5xU0xwNmFyU2VkT1lNbWFHWk03Zzd1UW4tdW9pU1VOWnF0VjZ0Z2dOb1drTjVUMFV6alA1dE5Pc1o2ODZaYmxmMFd3djZwT2VyaVZ4eVZ0dldFX3ROdU1obEFZWmNYYmJyallmd21vR0toS0RPQm5hWnl4c0VUb0kyUGlBSlJjSHVSYzhYQ1ZKUjM3d0ExMjBPQjQ0UG81bmJremJ5RE5lZF9ZMkhVa0FPTjlzU29WYjdTQ0FzRnRxV0RwX21SZDhyUWsxN0k0S3VELUxqVVNsdHcySi1fQjFLSzlFLUFhX183Xy1vQjRFNXZ5TTBpc0pBWnJTQkZUNU5TdXZiaTRpckkxNjFjS3RYOEE4dXhFbEZRVXJ5MUJyMlN1alZzWWtwTllhNG1uNzJmaS1adExYS2J6bEtpVnlFRzd0MXlINWpnZ3VNdk5ndHhaM0VMcDliOWREUmciLCJjbGllbnRfaWQiOiJiYWNrb2ZmaWNlX2xvb2t1cF93cml0ZSJ9.H2dSRsGa8Kn51MooA_WkzjtZHgZzEzB7uvjzggMYtmuVv-mMyP8p-f3lFm_I8Js6Wxf3kS6aR_qjsR-xASxryDj9QLYcP9TPH1KowzTmvL-E7d2YYHwAefhMetOHY341j7wLXGxWRBdKQnh1-b71rKV27YSJINO87_i29Z-0mzGsedS8LcYkdrviA3JkjHxHg2SCf9Si1CLGznDVreQXEnCEr2iERVwX2OmHYPY5BxK4WntQu-TmdhWyckHVI2o8qgtN5HrQe1ar8lVuhkXn1rWMVdb-EpVyls_Az8BZ89tK85uEJpZHRnbd-muceYBa0d3o8R2jPpJ1YGGkIVUksg' \
--header 'cache-control: private, no-cache, no-store, must-revalidate' \
--header 'x-tenant: 6180e4de152d227b72261039'

Resposne:
{
    "_id": "6a6f796fe6d0496d47421c01",
    "name": "sample",
    "isActive": true,
    "contracts": [
        "6a6f209d740731730e3b3350"
    ],
    "submit": true,
    "created_at": 1785690479909,
    "update_at": 1785690479909,
    "userDetail": {
        "userId": 41,
        "firstName": "sakthivel",
        "lastName": "sunder",
        "email": "sakthivel.sunder@almosafer.com",
        "userName": "sakthivel.sunder@almosafer.com",
        "createdBy": 23,
        "updatedBy": 52,
        "userAdditionalData": null,
        "blocked": false,
        "ssoUser": false,
        "countryCode": null,
        "phoneNumber": null,
        "isAdmin": false
    },
    "createdBy": "41",
    "autoId": 335
}




Curl Delete Group:
curl --location --request DELETE 'https://enigma-portal-staging.almosafer.com/api/dynamic-forms/smart_booking_group/6a6f79fce6d0496d47421c02' \
--header 'accept: application/json, text/javascript' \
--header 'accept-language: en-US,en;q=0.9' \
--header'authorization: Bearer eyJraWQiOiJqd3Qta2V5LWlkIiwidHlwIjoiSldUIiwiYWxnIjoiUlMyNTYifQ.eyJhdWQiOiJsb29rdXBfYWRtaW5fYXBpIiwidXNlcl9uYW1lIjoic2FrdGhpdmVsLnN1bmRlckBhbG1vc2FmZXIuY29tIiwic2NvcGUiOlsicmVhZCIsIndyaXRlIl0sImV4cCI6MTc4NTc1NDEwOCwiaWF0IjoxNzg1NjY3NzA4LCJqdGkiOiJleUowZVhBaU9pSktWMVFpTENKaGJHY2lPaUpTVXpJMU5pSjkuZXlKaGRXUWlPaUpzYjI5cmRYQmZZV1J0YVc1ZllYQnBJaXdpWlhod0lqb3hOemcxTnpVME1UQTRMQ0oxYzJWeVgyNWhiV1VpT2lKellXdDBhR2wyWld3dWMzVnVaR1Z5UUdGc2JXOXpZV1psY2k1amIyMGlMQ0pqYkdsbGJuUmZhV1FpT2lKaVlXTnJiMlptYVdObFgyeHZiMnQxY0Y5M2NtbDBaU0lzSW1wMGFTSTZJamhqWTJVM05ESmhMVGcwTXpZdE5EWTBaQzA1TWpobUxUQm1OemRtT0RNMlpUUXdaaUlzSW5OamIzQmxJanBiSW5KbFlXUWlMQ0ozY21sMFpTSmRmUS5xU0xwNmFyU2VkT1lNbWFHWk03Zzd1UW4tdW9pU1VOWnF0VjZ0Z2dOb1drTjVUMFV6alA1dE5Pc1o2ODZaYmxmMFd3djZwT2VyaVZ4eVZ0dldFX3ROdU1obEFZWmNYYmJyallmd21vR0toS0RPQm5hWnl4c0VUb0kyUGlBSlJjSHVSYzhYQ1ZKUjM3d0ExMjBPQjQ0UG81bmJremJ5RE5lZF9ZMkhVa0FPTjlzU29WYjdTQ0FzRnRxV0RwX21SZDhyUWsxN0k0S3VELUxqVVNsdHcySi1fQjFLSzlFLUFhX183Xy1vQjRFNXZ5TTBpc0pBWnJTQkZUNU5TdXZiaTRpckkxNjFjS3RYOEE4dXhFbEZRVXJ5MUJyMlN1alZzWWtwTllhNG1uNzJmaS1adExYS2J6bEtpVnlFRzd0MXlINWpnZ3VNdk5ndHhaM0VMcDliOWREUmciLCJjbGllbnRfaWQiOiJiYWNrb2ZmaWNlX2xvb2t1cF93cml0ZSJ9.H2dSRsGa8Kn51MooA_WkzjtZHgZzEzB7uvjzggMYtmuVv-mMyP8p-f3lFm_I8Js6Wxf3kS6aR_qjsR-xASxryDj9QLYcP9TPH1KowzTmvL-E7d2YYHwAefhMetOHY341j7wLXGxWRBdKQnh1-b71rKV27YSJINO87_i29Z-0mzGsedS8LcYkdrviA3JkjHxHg2SCf9Si1CLGznDVreQXEnCEr2iERVwX2OmHYPY5BxK4WntQu-TmdhWyckHVI2o8qgtN5HrQe1ar8lVuhkXn1rWMVdb-EpVyls_Az8BZ89tK85uEJpZHRnbd-muceYBa0d3o8R2jPpJ1YGGkIVUksg' \
--header 'x-tenant: 6180e4de152d227b72261039'  \
--header 'cache-control: private, no-cache, no-store, must-revalidate'


Resposne:
{
    "ok": 1
}



SmartBooking is on — set at least one supplier to SbGroup or Both


