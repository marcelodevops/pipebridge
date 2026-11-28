pipeline {
    agent any
    stages {
        stage('Matrix') {
            matrix {
                axes {
                    axis {
                        name 'ENV_NAME'
                        values "${BUILD_TYPE}-env", 'prod-env'
                    }
                }
                stages {
                    stage('Run') {
                        steps {
                            sh 'echo "Running in ${ENV_NAME}"'
                        }
                    }
                }
            }
        }
    }
}
