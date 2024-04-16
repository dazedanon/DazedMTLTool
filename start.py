print('Select which API type you want to use:')
print('1. cohere')
print('2. openai')
module_choice = input()

if module_choice == '1':
    from cohere_modules.main import main
    main()
elif module_choice == '2':
    from modules.main import main
    main()
else:
    print("Invalid input. Please enter '1' or '2'.")